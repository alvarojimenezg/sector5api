# Sector 5 API

A REST API built with **FastAPI** and **SQLAlchemy** for managing a FiveM server's database.

## Tech Stack

- FastAPI — High-performance Python web framework
- SQLAlchemy  — SQL toolkit & ORM
- Pydantic  — Data validation
- python-dotenv — Environment variable management

## Getting Started

### Prerequisites

- Python 3.10+
- A MySQL/MariaDB database (or compatible)

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/alvarojimenezg/sector5api.git

   cd sector5api

2. Create and activate a virtual environment:
    ```bash
    python -m venv env

    source env/bin/activate #Linux/MacOS
    env\Scripts\activate #Windows

3. Install dependencies:
    ```bash
    pip install fastapi uvicorn sqlalchemy python-dotenv pymysql

4. Create a .env file in the root directory with the following line:
    ```bash
    DATABASE_URL=mysql+pymysql://user:password@host:port/database

5. Running the API
    ```bash
    uvicorn main:app --reload