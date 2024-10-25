from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app import db, slack_bot
from app.scheduler import NotificationScheduler

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create tables in database
@app.on_event("startup")
async def startup():
    db.Base.metadata.create_all(bind=db.engine)
    
    # Initialize notification scheduler
    scheduler = NotificationScheduler(app)
    scheduler.init_scheduler()

# Include routes
app.include_router(slack_bot.router)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=6006)