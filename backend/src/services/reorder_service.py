import json,hashlib
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from ..models.network import BayesNetwork
from ..models.network_node import NetworkNode
from ..models.revision import CptRevision
from ..models.cpt_row import CptRow
from ..models.reorder import ReorderRecord
from ..models.common import serialize
from .network_service import nodes
from .revision_service import rows
from .reorder import convert,MAX_PARENTS
def summary(row):
 data=serialize(row);data.pop('states');return data
def expanded(row):return serialize(row)
def create(db,body):
 revision=db.get(CptRevision,body.revision_id)
 if not revision:raise HTTPException(422,'源概率版本不存在')
 network=db.get(BayesNetwork,revision.network_id)
 graph=nodes(db,network);cpt=rows(db,revision)
 try:result=convert(graph,cpt,list(body.order))
 except (ValueError,TypeError) as error:raise HTTPException(422,str(error))
 if db.scalar(select(BayesNetwork).where(BayesNetwork.name==body.network_name)):raise HTTPException(409,'网络名称已存在')
 if db.scalar(select(CptRevision).where(CptRevision.name==body.revision_name)):raise HTTPException(409,'版本名称已存在')
 fingerprint=hashlib.sha256(json.dumps({'nodes':graph,'cpt':cpt,'order':list(body.order)},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 new_network=BayesNetwork(id=str(uuid4()),name=body.network_name,description=body.description)
 new_revision=CptRevision(id=str(uuid4()),name=body.revision_name,network_id=new_network.id,version=body.version,description='由「%s / CPT %s」按新讲解顺序重排生成；%s'%(network.name,revision.version,body.description))
 detail={'source_network_id':network.id,'source_network_name':network.name,'source_revision_id':revision.id,'source_revision_name':revision.name,'source_version':revision.version,'source_nodes':graph,'new_network_name':body.network_name,'new_revision_name':body.revision_name,'new_version':body.version,'new_nodes':result['new_nodes'],'placements':result['placements'],'edges_before':result['edges_before'],'edges_after':result['edges_after'],'unidentifiable':result['unidentifiable'],'reconciliation':result['reconciliation'],'input_sha256':fingerprint,'max_parents':MAX_PARENTS,'method':'给定顺序的最小边数结构：逐节点在全部前驱中按(父节点数,父节点名称字典序)枚举首个使条件独立成立的父集；新CPT由log域联合分布边缘化；零概率父配置无法识别并补全0.5/0.5；极小正概率保持有限log值不当零；逐状态对账零模式精确比对。'}
 record=ReorderRecord(id=str(uuid4()),source_revision_id=revision.id,network_id=new_network.id,revision_id=new_revision.id,teaching_order=list(body.order),detail=detail,states=result['states'])
 try:
  db.add(new_network);db.flush()
  for node in result['new_nodes']:db.add(NetworkNode(id=str(uuid4()),network_id=new_network.id,**node))
  db.add(new_revision);db.flush()
  for row in result['new_rows']:db.add(CptRow(id=str(uuid4()),revision_id=new_revision.id,**row))
  db.add(record);db.commit()
 except IntegrityError:
  db.rollback();raise HTTPException(409,'名称或版本号冲突，未创建任何记录')
 except Exception:
  db.rollback();raise
 return record
