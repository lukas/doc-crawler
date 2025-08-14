from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from core.config import settings
from core.db import init_db
from api import issues, files, runs, rules, prs

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    yield
    # Shutdown
    pass

app = FastAPI(
    title="DocsQA API",
    description="W&B Documentation Quality Assurance System",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(issues.router, prefix="/api", tags=["issues"])
app.include_router(files.router, prefix="/api", tags=["files"])
app.include_router(runs.router, prefix="/api", tags=["runs"])
app.include_router(rules.router, prefix="/api", tags=["rules"])
app.include_router(prs.router, prefix="/api", tags=["prs"])

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "docsqa-api",
        "version": "1.0.0"
    }

@app.get("/")
async def root():
    return {
        "message": "DocsQA API",
        "docs": "/docs",
        "health": "/health"
    }

if __name__ == "__main__":
    import uvicorn
    config = settings.config
    uvicorn.run(
        "app:app", 
        host=config.server.host, 
        port=config.server.port, 
        reload=True
    )