"""Private Python tool adapter. No MCP, no generic URL/HTTP execution tool."""
import httpx
from .config import ERP_URL, INTERNAL_TOKEN


class AdapterError(ValueError):
    pass


class ERPAdapter:
    async def request(self,method,path,body=None):
        async with httpx.AsyncClient(timeout=30,trust_env=False) as client:
            try:
                response=await client.request(method,ERP_URL+path,json=body,headers={'X-Internal-Token':INTERNAL_TOKEN})
            except httpx.RequestError as exc:
                raise AdapterError('ERP/MES服务暂不可用') from exc
        if response.is_error:
            try:
                detail=response.json().get('detail','业务请求失败')
            except ValueError:
                detail='业务服务返回无效响应'
            raise AdapterError(str(detail))
        return response.json()

    async def catalog(self):
        return await self.request('GET','/catalog')

    async def query(self,sql):
        return await self.request('POST','/query',{'sql':sql})

    async def command(self,operation,params,request_id):
        return await self.request('POST','/commands/'+operation,{'params':params,'request_id':request_id})

    async def workflow(self,steps,inputs,request_id):
        return await self.request('POST','/workflow',{'steps':steps,'inputs':inputs,'request_id':request_id})


erp=ERPAdapter()
