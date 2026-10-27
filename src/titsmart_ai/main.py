"""Entry point for running the application."""
import uvicorn
from titsmart_ai.config import settings
from titsmart_ai.api.main import app

if __name__ == "__main__":
    uvicorn.run("titsmart_ai.api.main:app", host="127.0.0.1", port=settings.PORT, reload=settings.DEBUG)
