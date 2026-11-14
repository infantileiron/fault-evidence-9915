from sqlalchemy import String,Text,JSON,ForeignKey,Double,Boolean
from sqlalchemy.orm import Mapped,mapped_column
from .common import RecordMixin
from ..config.database import Base
class ReorderRecord(RecordMixin,Base):
 __tablename__="reorders"
 source_revision_id:Mapped[str]=mapped_column(ForeignKey("revisions.id"))
 network_id:Mapped[str]=mapped_column(ForeignKey("networks.id"))
 revision_id:Mapped[str]=mapped_column(ForeignKey("revisions.id"))
 teaching_order:Mapped[dict]=mapped_column(JSON)
 detail:Mapped[dict]=mapped_column(JSON)
 states:Mapped[dict]=mapped_column(JSON)
