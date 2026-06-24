from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.router import router
from app.core.config import get_settings
from app.core.database import SessionLocal, engine
from app.core.schema_compat import ensure_sqlite_phase2_columns
from app.models import Base, Customer
from app.seed import ensure_phase2b_seed_data, ensure_phase2c_seed_data, seed_database, seed_scale_test_data
from app.services.scheduler import start_scheduler_if_enabled

settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_phase2_columns(engine)
    if settings.auto_seed:
        db = SessionLocal()
        try:
            has_seed = db.scalar(select(Customer.id).limit(1))
            if has_seed is None:
                seed_database(db)
                db.commit()
            ensure_phase2b_seed_data(db)
            ensure_phase2c_seed_data(db)
            db.commit()
            if settings.auto_seed_scale:
                seed_scale_test_data(
                    db,
                    customer_count=settings.scale_seed_customer_count,
                    jobs_per_customer=settings.scale_seed_jobs_per_customer,
                )
                db.commit()
        finally:
            db.close()
    start_scheduler_if_enabled(settings)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}
