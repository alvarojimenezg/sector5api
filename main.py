from fastapi import FastAPI, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Annotated
from database import engine, SessionLocal, metadata
from sqlalchemy.orm import Session
from sqlalchemy import select

app = FastAPI()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

db_dependency = Annotated[Session, Depends(get_db)]

@app.get("/users", status_code=status.HTTP_200_OK)
async def get_all_users(db: db_dependency):
    users_table = metadata.tables['users']
    
    query = select(users_table)
    result = db.execute(query)
    users = result.fetchall()
    
    users_list = [dict(row._mapping) for row in users]
    
    return {"users": users_list}

@app.get("/users/{user_id}", status_code=status.HTTP_200_OK)
async def get_user_by_identifier(identifier: str, db: db_dependency):
    users_table = metadata.tables['users']

    query = select(users_table).where(users_table.c.identifier == identifier)
    result = db.execute(query)
    user = result.fetchone()

    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return {"user": dict(user._mapping)}