import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.errors import BillingError

app = FastAPI(
    title="Usage Metering and Billing Engine",
    description="Tenant-scoped usage metering, quota enforcement, and simulated billing.",
    version="0.1.0",
)


@app.exception_handler(BillingError)
async def billing_error_handler(request: Request, error: BillingError) -> JSONResponse:
    logging.getLogger(__name__).info("Request rejected: %s", error.code)
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "context": error.context,
            }
        },
    )


app.include_router(router)
