from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import DateTime, BigInteger, Float, Integer, ForeignKey, func
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
    
    # Subscription & Limits
    is_premium: Mapped[bool] = mapped_column(default=False)
    premium_until: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    daily_usage_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    last_usage_date: Mapped[datetime] = mapped_column(DateTime, default=utc_now) # Storing full datetime but logic uses date

class VoiceMessage(Base):
    __tablename__ = "voice_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    duration_seconds: Mapped[float] = mapped_column(Float)
    transcription_length_chars: Mapped[int] = mapped_column(Integer)
    processing_time_seconds: Mapped[float] = mapped_column(Float)

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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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

async def add_voice_message(user_id: int, duration: float, chars: int, process_time: float):
    async with async_session() as session:
        msg = VoiceMessage(
            user_id=user_id,
            duration_seconds=duration,
            transcription_length_chars=chars,
            processing_time_seconds=process_time
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

async def check_user_limit(user_id: int, duration: float) -> bool:
    """Returns True if user can process file, False if limit exceeded."""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return True # New user logic handled elsewhere, or allow first time
        
        if user.is_premium:
            return True
            
        now = utc_now()
        
        # Check if new day (UTC)
        if user.last_usage_date.date() < now.date():
            user.daily_usage_seconds = 0.0
            user.last_usage_date = now
            await session.commit()
            
        # Limit: 10 minutes = 600 seconds
        if user.daily_usage_seconds + duration > 300:
            return False
            
        return True

async def update_user_usage(user_id: int, duration: float):
    async with async_session() as session:
        user = await session.get(User, user_id)
        if user:
            user.daily_usage_seconds += duration
            user.last_usage_date = utc_now()
            await session.commit()

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
        
        # Today (Since midnight UTC)
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
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
            "is_premium": user.is_premium,
            "premium_until": user.premium_until,
            "daily_usage": round(user.daily_usage_seconds / 60, 2) # in minutes
        }

