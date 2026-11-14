from sqlalchemy import select
from ..models.reorder import ReorderRecord
from ..services import reorder_service as service
from .common import require
def list_all(db):return [service.summary(row) for row in db.scalars(select(ReorderRecord).order_by(ReorderRecord.created_at.desc())).all()]
def detail(db,ident):return service.expanded(require(db,ReorderRecord,ident))
def create(db,body):return service.expanded(service.create(db,body))
