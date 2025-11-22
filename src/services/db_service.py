from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import DateTime, BigInteger, Float, Integer, ForeignKey, func
from datetime import datetime
from src.config import DATABASE_URL

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True) # Telegram ID
    username: Mapped[str] = mapped_column(nullable=True)
    first_name: Mapped[str] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class VoiceMessage(Base):
    __tablename__ = "voice_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    duration_seconds: Mapped[float] = mapped_column(Float)
    transcription_length_chars: Mapped[int] = mapped_column(Integer)
    processing_time_seconds: Mapped[float] = mapped_column(Float)

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
            user.last_activity_at = datetime.utcnow()
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
            user.last_activity_at = datetime.utcnow()
            
        await session.commit()

async def get_user_stats(user_id: int):
    async with async_session() as session:
        # Basic counts
        total_msgs = await session.scalar(
            func.count(VoiceMessage.id).filter(VoiceMessage.user_id == user_id)
        ) or 0
        
        # 30 days
        thirty_days_ago = datetime.utcnow().timestamp() - 30 * 24 * 60 * 60
        msgs_30d = await session.scalar(
            func.count(VoiceMessage.id).filter(
                VoiceMessage.user_id == user_id,
                VoiceMessage.created_at >= datetime.fromtimestamp(thirty_days_ago)
            )
        ) or 0
        
        # 7 days
        seven_days_ago = datetime.utcnow().timestamp() - 7 * 24 * 60 * 60
        msgs_7d = await session.scalar(
            func.count(VoiceMessage.id).filter(
                VoiceMessage.user_id == user_id,
                VoiceMessage.created_at >= datetime.fromtimestamp(seven_days_ago)
            )
        ) or 0
        
        # Averages
        avg_length = await session.scalar(
            func.avg(VoiceMessage.duration_seconds).filter(VoiceMessage.user_id == user_id)
        ) or 0
        
        avg_chars = await session.scalar(
            func.avg(VoiceMessage.transcription_length_chars).filter(VoiceMessage.user_id == user_id)
        ) or 0

        user = await session.get(User, user_id)
        
        return {
            "user_id": user_id,
            "reg_date": user.created_at,
            "last_activity": user.last_activity_at,
            "total_msgs": total_msgs,
            "msgs_30d": msgs_30d,
            "msgs_7d": msgs_7d,
            "avg_length_sec": round(float(avg_length), 2),
            "avg_chars": round(float(avg_chars), 2)
        }

