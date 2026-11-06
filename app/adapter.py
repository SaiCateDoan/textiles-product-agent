"""Private Python tool adapter. No MCP, no generic URL/HTTP execution tool."""
import asyncio
import httpx
from .auth import current_actor
from .config import ERP_URL, INTERNAL_TOKEN


class AdapterError(ValueError):
    pass


class ERPAdapter:
    def __init__(self):
        self._client=None

    async def start(self):
        if self._client is None:
            self._client=httpx.AsyncClient(timeout=30,trust_env=False)

    async def close(self):
        client,self._client=self._client,None
        if client is not None:
            await client.aclose()

    async def request(self,method,path,body=None):
        if self._client is None:
            raise AdapterError('业务适配器尚未启动')
        # Identity belongs to this request, never to the shared client's defaults.
        headers={'X-Internal-Token':INTERNAL_TOKEN}
        if path!='/health': headers['X-Actor-Session']=(await asyncio.to_thread(current_actor))['session_hash']
        try:
            response=await self._client.request(method,ERP_URL+path,json=body,headers=headers)
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

    async def dashboard(self):
        return await self.request('GET','/dashboard')

    async def query(self,sql):
        return await self.request('POST','/query',{'sql':sql})

    async def command(self,operation,params,request_id):
        return await self.request('POST','/commands/'+operation,{'params':params,'request_id':request_id})

    async def workflow(self,steps,inputs,request_id):
        return await self.request('POST','/workflow',{'steps':steps,'inputs':inputs,'request_id':request_id})


erp=ERPAdapter()
