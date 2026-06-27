from fastapi import FastAPI

app = FastAPI(title="Patent Agent")


@app.get("/health")
def health_check() -> dict[str, str]:
    """返回服务健康检查状态。

    Returns:
        固定健康状态,用于确认 API 服务已启动。
    """
    return {"status": "ok"}
