from pydantic import BaseModel,ConfigDict,Field
class ReorderCreate(BaseModel):
 model_config=ConfigDict(extra='forbid')
 revision_id:str
 order:list[str]=Field(min_length=1,max_length=10)
 network_name:str=Field(min_length=2,max_length=180)
 revision_name:str=Field(min_length=2,max_length=180)
 version:str=Field(default='r1',min_length=1,max_length=40)
 description:str=Field(default='',max_length=3000)
