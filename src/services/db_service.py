from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import DateTime, BigInteger, Float, Integer, ForeignKey, func, String, Text
from datetime import datetime, timezone
from src.config import DATABASE_URL

class Base(DeclarativeBase):
    pass

def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True) # Telegram ID
    username: Mapped[str] = mapped_column(nullable=True)
    first_name: Mapped[str] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    
    # Balance & Usage
    balance_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    used_free_seconds: Mapped[float] = mapped_column(Float, default=0.0)

class Transaction(Base):
    __tablename__ = "transactions"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    provider: Mapped[str] = mapped_column(String) # 'yookassa', 'telegram_stars'
    amount_rub: Mapped[float] = mapped_column(Float)
    seconds_added: Mapped[float] = mapped_column(Float)
    payment_id: Mapped[str] = mapped_column(String, nullable=True) # External ID
    status: Mapped[str] = mapped_column(String, default="pending") # pending, success, failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

class VoiceMessage(Base):
    __tablename__ = "voice_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    duration_seconds: Mapped[float] = mapped_column(Float)
    transcription_length_chars: Mapped[int] = mapped_column(Integer, nullable=True) # Nullable for failed
    processing_time_seconds: Mapped[float] = mapped_column(Float, nullable=True) # Nullable for failed
    status: Mapped[str] = mapped_column(String, default="success") # success, failed
    error_reason: Mapped[str] = mapped_column(String, nullable=True) # compression_failed, too_large, etc.
    transcription_text: Mapped[str] = mapped_column(Text, nullable=True) # Stored transcription

class Review(Base):
    __tablename__ = "reviews"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    feedback_type: Mapped[str] = mapped_column() # 'positive', 'negative_reason', 'negative_custom', 'suggestion'
    content: Mapped[str] = mapped_column(nullable=True)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    retries = 5
    while retries > 0:
        try:
            async with engine.begin() as conn:
                # Note: This won't migrate existing tables if columns change. 
                # In prod we should use alembic, but for now we might need to drop tables manually if schema changes drastically.
                # Since we are changing User schema significantly, assume we handle it (or use a fresh DB).
                await conn.run_sync(Base.metadata.create_all)
            return
        except Exception as e:
            retries -= 1
            if retries == 0:
                raise e
            import asyncio
            import logging
            logging.warning(f"Database not ready, retrying in 5 seconds... ({retries} attempts left)")
            await asyncio.sleep(5)

async def get_or_create_user(user_id: int, username: str, first_name: str):
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            user = User(id=user_id, username=username, first_name=first_name)
            session.add(user)
        else:
            # Update info if changed
            user.username = username
            user.first_name = first_name
            user.last_activity_at = utc_now()
        await session.commit()
        return user

async def add_voice_message(user_id: int, duration: float, chars: int = 0, process_time: float = 0.0, status: str = "success", error: str = None, text: str = None):
    async with async_session() as session:
        msg = VoiceMessage(
            user_id=user_id,
            duration_seconds=duration,
            transcription_length_chars=chars,
            processing_time_seconds=process_time,
            status=status,
            error_reason=error,
            transcription_text=text
        )
        session.add(msg)
        
        # Update user last activity
        user = await session.get(User, user_id)
        if user:
            user.last_activity_at = utc_now()
            
        await session.commit()

async def add_review(user_id: int, feedback_type: str, content: str = None):
    async with async_session() as session:
        review = Review(
            user_id=user_id,
            feedback_type=feedback_type,
            content=content
        )
        session.add(review)
        await session.commit()

from sqlalchemy import select

async def check_user_limit(user_id: int, duration: float) -> tuple[bool, float]:
    """Returns (True, 0) if allowed, (False, missing_seconds) if limit exceeded."""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return True, 0.0 # Allow, will be created later
        
        remaining_free = max(0.0, 300 - user.used_free_seconds)
        total_available = remaining_free + user.balance_seconds
        
        if total_available >= duration:
            return True, 0.0
        else:
            missing = duration - total_available
            return False, missing

async def update_user_usage(user_id: int, duration: float):
    async with async_session() as session:
        user = await session.get(User, user_id)
        if user:
            remaining_free = max(0, 300 - user.used_free_seconds)
            
            if remaining_free > 0:
                if duration <= remaining_free:
                    user.used_free_seconds += duration
                else:
                    # Consume all free, rest from balance
                    user.used_free_seconds = 300.0
                    to_deduct = duration - remaining_free
                    user.balance_seconds = max(0.0, user.balance_seconds - to_deduct)
            else:
                user.balance_seconds = max(0.0, user.balance_seconds - duration)
                
            user.last_activity_at = utc_now()
            await session.commit()

async def create_transaction(user_id: int, provider: str, amount: float, seconds: float, payment_id: str = None):
    async with async_session() as session:
        tx = Transaction(
            user_id=user_id,
            provider=provider,
            amount_rub=amount,
            seconds_added=seconds,
            payment_id=payment_id,
            status="pending"
        )
        session.add(tx)
        await session.commit()
        return tx.id

async def get_transaction(tx_id: int):
    async with async_session() as session:
        return await session.get(Transaction, tx_id)

async def complete_transaction(tx_id: int, status: str = "success"):
    async with async_session() as session:
        tx = await session.get(Transaction, tx_id)
        if tx and tx.status == "pending":
            tx.status = status
            if status == "success":
                user = await session.get(User, tx.user_id)
                if user:
                    user.balance_seconds += tx.seconds_added
            await session.commit()
            return True
        return False

async def get_user_stats(user_id: int):
    async with async_session() as session:
        # Basic counts
        stmt_total = select(func.count(VoiceMessage.id)).where(VoiceMessage.user_id == user_id)
        total_msgs = await session.scalar(stmt_total) or 0
        
        # 30 days
        thirty_days_ago = datetime.now(timezone.utc).timestamp() - 30 * 24 * 60 * 60
        stmt_30d = select(func.count(VoiceMessage.id)).where(
            VoiceMessage.user_id == user_id,
            VoiceMessage.created_at >= datetime.fromtimestamp(thirty_days_ago)
        )
        msgs_30d = await session.scalar(stmt_30d) or 0
        
        # 7 days
        seven_days_ago = datetime.now(timezone.utc).timestamp() - 7 * 24 * 60 * 60
        stmt_7d = select(func.count(VoiceMessage.id)).where(
            VoiceMessage.user_id == user_id,
            VoiceMessage.created_at >= datetime.fromtimestamp(seven_days_ago)
        )
        msgs_7d = await session.scalar(stmt_7d) or 0
        
        # Today
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
        stmt_today = select(func.count(VoiceMessage.id)).where(
            VoiceMessage.user_id == user_id,
            VoiceMessage.created_at >= today_start
        )
        msgs_today = await session.scalar(stmt_today) or 0
        
        # Averages
        stmt_avg_len = select(func.avg(VoiceMessage.duration_seconds)).where(VoiceMessage.user_id == user_id)
        avg_length = await session.scalar(stmt_avg_len) or 0
        
        stmt_avg_chars = select(func.avg(VoiceMessage.transcription_length_chars)).where(VoiceMessage.user_id == user_id)
        avg_chars = await session.scalar(stmt_avg_chars) or 0

        user = await session.get(User, user_id)
        
        if not user:
            return {
                "user_id": user_id,
                "reg_date": utc_now(),
                "last_activity": utc_now(),
                "total_msgs": 0,
                "msgs_30d": 0,
                "msgs_7d": 0,
                "msgs_today": 0,
                "avg_length_sec": 0,
                "avg_chars": 0,
                "balance_minutes": 0,
                "free_left_minutes": 5.0 # Default 300 sec
            }

        remaining_free = max(0, 300 - user.used_free_seconds)
        
        return {
            "user_id": user_id,
            "reg_date": user.created_at,
            "last_activity": user.last_activity_at,
            "total_msgs": total_msgs,
            "msgs_30d": msgs_30d,
            "msgs_7d": msgs_7d,
            "msgs_today": msgs_today,
            "avg_length_sec": round(float(avg_length), 2),
            "avg_chars": round(float(avg_chars), 2),
            "balance_minutes": round(user.balance_seconds / 60, 1),
            "free_left_minutes": round(remaining_free / 60, 1)
        }
