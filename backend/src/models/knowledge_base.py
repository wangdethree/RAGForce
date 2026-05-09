from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin, gen_uuid


class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    top_k: Mapped[int] = mapped_column(default=5)
    similarity_threshold: Mapped[float] = mapped_column(default=0.7)
    document_count: Mapped[int] = mapped_column(default=0)

    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")
