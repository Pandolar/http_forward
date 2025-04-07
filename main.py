import logging
from fastapi import FastAPI, Request
from fastapi.responses import Response
import httpx
import asyncio
import uvicorn
import json
from datetime import datetime
import yaml
from pathlib import Path
from typing import List, Dict, Any
import sys

# 配置加载
def load_config() -> Dict[str, Any]:
    config_path = Path(__file__).parent / "config.yml"
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"加载配置文件失败: {str(e)}")
        sys.exit(1)

CONFIG = load_config()

# 日志配置
def setup_logging():
    logging.basicConfig(
        level=CONFIG.get('logging_level', 'INFO'),
        format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": %(message)s}',
        handlers=[
            logging.FileHandler(CONFIG.get('log_file', 'forwarder.log')),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

app = FastAPI()

async def log_request(request: Request) -> Dict[str, Any]:
    """记录请求信息并返回日志字典"""
    body = await request.body()
    try:
        body_data = json.loads(body.decode()) if body else None
    except:
        body_data = body.decode() if body else None
    
    log_data = {
        "time": datetime.now().isoformat(),
        "method": request.method,
        "url": str(request.url),
        "client_ip": request.client.host if request.client else None,
        "headers": dict(request.headers),
        "query_params": dict(request.query_params),
        "body": body_data
    }
    logger.info(json.dumps(log_data, ensure_ascii=False))
    return log_data

async def forward_request(client: httpx.AsyncClient, url: str, request: Request, log_data: Dict[str, Any]) -> httpx.Response:
    """转发请求到指定URL"""
    try:
        body = await request.body()
        headers = dict(request.headers)
        headers.pop('host', None)
        
        full_url = f"{url}?{request.url.query}" if request.url.query else url
        
        forward_log = {
            **log_data,
            "forward_url": full_url,
            "action": "forwarding_request"
        }
        logger.debug(json.dumps(forward_log, ensure_ascii=False))
        
        response = await client.request(
            method=request.method,
            url=full_url,
            headers=headers,
            content=body,
            follow_redirects=True
        )
        
        response_log = {
            **log_data,
            "forward_url": full_url,
            "status_code": response.status_code,
            "response_size": len(response.content),
            "action": "received_response"
        }
        logger.debug(json.dumps(response_log, ensure_ascii=False))
        
        return response
        
    except Exception as e:
        error_log = {
            **log_data,
            "forward_url": url,
            "error": str(e),
            "action": "forwarding_error"
        }
        logger.error(json.dumps(error_log, ensure_ascii=False))
        raise

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def forward(request: Request, path: str):
    # 记录请求日志
    log_data = await log_request(request)
    
    async with httpx.AsyncClient() as client:
        tasks = []
        for i, url in enumerate(CONFIG['forward_urls']):
            is_primary = (i == 0)
            task = forward_request(client, url, request, log_data)
            if is_primary:
                # 主URL任务放在第一位
                tasks.insert(0, task)
            else:
                tasks.append(task)
        
        try:
            responses = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(json.dumps({
                **log_data,
                "error": str(e),
                "action": "forwarding_failed"
            }, ensure_ascii=False))
            return Response(
                content=json.dumps({"error": "Forwarding failed"}),
                status_code=500,
                media_type='application/json'
            )

        # 处理主响应
        primary_response = responses[0] if responses else None
        if primary_response and isinstance(primary_response, httpx.Response):
            headers = dict(primary_response.headers)
            headers.pop('content-encoding', None)
            headers.pop('content-length', None)
            headers.pop('transfer-encoding', None)
            
            return Response(
                content=primary_response.content,
                status_code=primary_response.status_code,
                headers=headers,
                media_type=primary_response.headers.get('content-type')
            )
        
        return Response(
            content=json.dumps({"error": "No valid response from primary URL"}),
            status_code=502,
            media_type='application/json'
        )

if __name__ == "__main__":
    logger.info("转发服务器启动", extra={
        "host": CONFIG.get('host', '0.0.0.0'),
        "port": CONFIG.get('port', 8190)
    })
    uvicorn.run(
        app,
        host=CONFIG.get('host', '0.0.0.0'),
        port=CONFIG.get('port', 8190),
        log_config=None
    )