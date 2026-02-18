import json
import os
from typing import Annotated, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import SessionLocal, metadata

app = FastAPI()

HTTP_TIMEOUT_SECONDS = float(os.getenv("FIVEM_HTTP_TIMEOUT", "5"))
DEFAULT_FIVEM_SERVER_URL = os.getenv("FIVEM_SERVER_URL")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


db_dependency = Annotated[Session, Depends(get_db)]


#Normalize FiveM Server URL
def normalize_base_url(url: str) -> str:
    clean_url = (url or "").strip().rstrip("/")
    if not clean_url:
        raise ValueError("FIVEM_SERVER_URL no puede estar vacio.")

    parsed = urlparse(clean_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("FIVEM_SERVER_URL debe usar http o https.")
    if not parsed.netloc:
        raise ValueError("FIVEM_SERVER_URL no es valido.")

    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")


#Build Fivem Server URL Candidates
def build_fivem_candidates(base_url: str) -> list[str]:
    normalized = normalize_base_url(base_url)
    parsed = urlparse(normalized)
    candidates = [normalized]

    if parsed.port and parsed.port >= 40000:
        alt_port = parsed.port - 10000
        if alt_port > 0 and parsed.hostname:
            alt_netloc = f"{parsed.hostname}:{alt_port}"
            alt_url = urlunparse((parsed.scheme, alt_netloc, "", "", "", "")).rstrip("/")
            if alt_url not in candidates:
                candidates.append(alt_url)

    return candidates


def parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fetch_json_from_candidate(candidate: str, path: str) -> Any:
    request = Request(
        f"{candidate}{path}",
        headers={"Accept": "application/json", "User-Agent": "sector5api/1.0"},
    )

    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        body = response.read().decode("utf-8", errors="replace")

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Respuesta no JSON en {candidate}{path}") from exc


def pick_hostname(dynamic_data: dict[str, Any], info_data: dict[str, Any]) -> str | None:
    dynamic_hostname = dynamic_data.get("hostname")
    if isinstance(dynamic_hostname, str) and dynamic_hostname.strip():
        return dynamic_hostname.strip()

    info_vars = info_data.get("vars")
    if isinstance(info_vars, dict):
        project_name = info_vars.get("sv_projectName")
        if isinstance(project_name, str) and project_name.strip():
            return project_name.strip()

    return None


def map_player(player: Any, index: int) -> dict[str, Any]:
    if not isinstance(player, dict):
        return {
            "id": f"player-{index + 1}",
            "name": f"Jugador {index + 1}",
            "identifier": None,
            "ping": None,
        }

    player_id = player.get("id")
    player_name = player.get("name")
    ping = parse_int(player.get("ping"))

    identifiers = player.get("identifiers")
    identifier = None
    if isinstance(identifiers, list):
        for value in identifiers:
            if isinstance(value, str) and value.strip():
                identifier = value.strip()
                break

    return {
        "id": str(player_id) if player_id is not None else f"player-{index + 1}",
        "name": player_name.strip() if isinstance(player_name, str) and player_name.strip() else f"Jugador {index + 1}",
        "identifier": identifier,
        "ping": ping,
    }


def collect_fivem_overview(base_url: str) -> dict[str, Any]:
    errors: list[str] = []

    for candidate in build_fivem_candidates(base_url):
        try:
            dynamic_data = fetch_json_from_candidate(candidate, "/dynamic.json")
            players_data = fetch_json_from_candidate(candidate, "/players.json")
            info_data = fetch_json_from_candidate(candidate, "/info.json")
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            errors.append(f"{candidate}: {exc}")
            continue

        if not isinstance(dynamic_data, dict):
            dynamic_data = {}
        if not isinstance(info_data, dict):
            info_data = {}

        raw_players = players_data if isinstance(players_data, list) else []
        players = [map_player(player, index) for index, player in enumerate(raw_players)]

        players_online = parse_int(dynamic_data.get("clients"))
        if players_online is None:
            players_online = len(players)

        players_max = parse_int(dynamic_data.get("sv_maxclients"))
        if players_max is None:
            vars_data = info_data.get("vars")
            if isinstance(vars_data, dict):
                players_max = parse_int(vars_data.get("sv_maxClients"))

        return {
            "reachable": True,
            "source_url": candidate,
            "hostname": pick_hostname(dynamic_data, info_data),
            "players_online": players_online,
            "players_max": players_max,
            "players": players[:50],
            "error": None,
        }

    return {
        "reachable": False,
        "source_url": None,
        "hostname": None,
        "players_online": 0,
        "players_max": None,
        "players": [],
        "error": errors[-1] if errors else "No se pudo conectar con FiveM.",
    }

def fetch_all(db: Session, table_name: str) -> list[dict]:
    table = metadata.tables[table_name]
    query = select(table)
    result = db.execute(query)
    return [dict(row._mapping) for row in result.fetchall()]

def fetch_one(db: Session, table_name: str, column: str, value) -> dict:
    table = metadata.tables[table_name]
    query = select(table).where(table.c[column] == value)
    result = db.execute(query)
    row = result.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{table_name} record not found")
    return dict(row._mapping)

def fetch_many(db: Session, table_name: str, column: str, value) -> dict:
    table = metadata.tables[table_name]
    query = select(table).where(table.c[column] == value)
    result = db.execute(query)
    return [dict(row._mapping) for row in result.fetchall()]

#USER RELATED ENDPOINTS
@app.get("/users", status_code=status.HTTP_200_OK)
async def get_all_users(db: db_dependency):
    return {"users": fetch_all(db, "users")}

@app.get("/users/by-id/{userId}", status_code=status.HTTP_200_OK)
async def get_user_by_id(userId: str, db: db_dependency):
    return {"user": fetch_one(db, "users", "userId", userId)}

#PLAYER RELATED ENDPOINTS
@app.get("/players", status_code=status.HTTP_200_OK)
async def get_all_players(db: db_dependency):
    return {"players": fetch_all(db, "players")}

@app.get("/players/properties", status_code=status.HTTP_200_OK)
async def get_all_properties(db: db_dependency):
    return {"properties": fetch_all(db, "properties")}

@app.get("/players/by-id/{owner}/properties", status_code=status.HTTP_200_OK)
async def get_player_owned_properties(owner: str, db: db_dependency):
    return {"properties": fetch_many(db, "properties", "owner", owner)}

@app.get("/players/vehicles", status_code=status.HTTP_200_OK)
async def get_all_player_vehicles(db: db_dependency):
    return {"player_vehicles": fetch_all(db, "player_vehicles")}

@app.get("/players/by-id/{citizenid}/vehicles", status_code=status.HTTP_200_OK)
async def get_player_vehicles(citizenid: str, db: db_dependency):
    return {"player_vehicles": fetch_many(db, "player_vehicles", "citizenid", citizenid)}

@app.get("/server/overview", status_code=status.HTTP_200_OK)
async def get_server_overview():
    try:
        return collect_fivem_overview(DEFAULT_FIVEM_SERVER_URL)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
