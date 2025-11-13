"""Device registration helpers.

Behavior on startup (register_device_auto):
- read hardware serial from /proc/cpuinfo (Raspberry Pi)
- check local DB for kiosk with matching serial -> return if found
- if Firestore configured, query kiosks collection for document where serialNumber == serial
  - if found: use that document id/data and persist locally
  - if not found: generate a kiosk-id (kiosk-###), create Firestore doc with that id, persist locally
- if Firestore not configured: generate kiosk-id locally and persist locally

This implements the flow you described: collect identity, check local DB, post to backend/Firestore
and persist the returned kiosk info locally.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from . import state
import time
import json
import os
import re
import socket

try:
    from . import sync
except Exception:
    sync = None

router = APIRouter()


def _ensure_kiosk_table(conn):
    # keep a single source of truth for Firestore-origin kiosks in kiosks_fs
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kiosks_fs (
            fs_id TEXT PRIMARY KEY,
            name TEXT,
            serialNumber TEXT,
            assignedRoomId TEXT,
            ipAddress TEXT,
            macAddress TEXT,
            status TEXT,
            installedAt TEXT,
            updatedAt TEXT,
            raw_doc JSON
        )
    """
    )


def _read_rpi_serial():
    # Read Raspberry Pi serial from /proc/cpuinfo if available
    try:
        if os.path.exists("/proc/cpuinfo"):
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if line.strip().startswith("Serial"):
                        parts = line.split(":")
                        if len(parts) >= 2:
                            return parts[1].strip()
    except Exception:
        pass
    return None


def _detect_ip_address():
    """Return the primary non-loopback IPv4 address for this host (best-effort)."""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # doesn't need to be reachable
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            # fallback to hostname resolution
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return None


def _detect_mac_address():
    """Best-effort read of MAC address: read from /sys/class/net for first non-loopback interface."""
    try:
        import os
        net_dir = "/sys/class/net"
        if os.path.isdir(net_dir):
            for iface in os.listdir(net_dir):
                if iface == "lo":
                    continue
                addr_path = os.path.join(net_dir, iface, "address")
                state_path = os.path.join(net_dir, iface, "operstate")
                try:
                    with open(addr_path, "r") as f:
                        mac = f.read().strip()
                    # prefer interfaces that are up
                    up = False
                    try:
                        with open(state_path, "r") as sf:
                            up = sf.read().strip() == "up"
                    except Exception:
                        up = False
                    if mac and mac != "00:00:00:00:00:00":
                        return mac
                except Exception:
                    continue
    except Exception:
        pass
    return None


def _next_kiosk_id(conn):
    # find existing kiosk ids like kiosk-### and increment highest, start at 201
    try:
        cur = conn.cursor()
        cur.execute("SELECT fs_id FROM kiosks_fs")
        rows = cur.fetchall()
        max_n = 200
        pattern = re.compile(r"kiosk[-_]?([0-9]+)$", re.IGNORECASE)
        for r in rows:
            if not r or not r[0]:
                continue
            m = pattern.search(str(r[0]))
            if m:
                try:
                    n = int(m.group(1))
                    if n > max_n:
                        max_n = n
                except Exception:
                    continue
        return f"kiosk-{max_n + 1}"
    except Exception:
        return "kiosk-201"


def _write_local_kiosk(conn, kiosk_id, name, serial, assigned_room, ip, mac, status, installed_at, updated_at, raw):
    _ensure_kiosk_table(conn)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO kiosks_fs (fs_id, name, serialNumber, assignedRoomId, ipAddress, macAddress, status, installedAt, updatedAt, raw_doc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (kiosk_id, name, serial or "", assigned_room, ip, mac, status, installed_at, updated_at, json.dumps(raw) if raw is not None else None),
    )
    conn.commit()


def register_device_auto():
    """Auto-register device at startup following the flow:
    - read serial/hostname
    - check local DB for serial
    - if found, return local row
    - else, if Firestore available, search kiosks where serialNumber==serial
        - if found, persist locally and return
        - if not found, create a new kiosk doc with generated id, persist to FS and locally
    - if Firestore not available, create locally with generated id
    """
    try:
        serial = _read_rpi_serial()
        hostname = socket.gethostname()
        conn = state.get_db()
        _ensure_kiosk_table(conn)
        cur = conn.cursor()

        # 1) check local DB first (use kiosks_fs as single local kiosk table)
        if serial:
            cur.execute(
                "SELECT fs_id, name, serialNumber, assignedRoomId, ipAddress, macAddress, status, installedAt, updatedAt, raw_doc FROM kiosks_fs WHERE serialNumber = ?",
                (serial,),
            )
            row = cur.fetchone()
            if row:
                return {
                    "id": row[0],
                    "name": row[1],
                    "serialNumber": row[2],
                    "assignedRoomId": row[3],
                    "ipAddress": row[4],
                    "macAddress": row[5],
                    "status": row[6],
                    "installedAt": row[7],
                    "updatedAt": row[8],
                }
        else:
            # If no serial (non-RPi or unreadable), try matching by hostname or use first kiosk as fallback
            try:
                cur.execute("SELECT fs_id, name, serialNumber, assignedRoomId, ipAddress, macAddress, status, installedAt, updatedAt, raw_doc FROM kiosks_fs WHERE name = ? OR fs_id = ? LIMIT 1", (hostname, hostname))
                row = cur.fetchone()
                if row:
                    return {
                        "id": row[0],
                        "name": row[1],
                        "serialNumber": row[2],
                        "assignedRoomId": row[3],
                        "ipAddress": row[4],
                        "macAddress": row[5],
                        "status": row[6],
                        "installedAt": row[7],
                        "updatedAt": row[8],
                    }
            except Exception:
                pass

        # 2) Not found locally. If Firestore available, search there by serialNumber
        db_fs = getattr(sync, "db_fs", None) if sync is not None else None
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")

        if db_fs and serial:
            try:
                # Query kiosks collection for matching serialNumber
                docs = list(db_fs.collection("kiosks").where("serialNumber", "==", serial).stream())
                if docs:
                    # Use first matching doc
                    doc = docs[0]
                    data = doc.to_dict() or {}
                    kiosk_id = doc.id
                    name = data.get("name") or hostname or kiosk_id
                    assignedRoomId = data.get("assignedRoomId") or None
                    ip = data.get("ipAddress") or data.get("ip") or None
                    mac = data.get("macAddress") or None
                    status = data.get("status") or "online"
                    installedAt = data.get("installedAt") or now
                    updatedAt = data.get("updatedAt") or now
                    # persist locally into kiosks_fs
                    _write_local_kiosk(conn, kiosk_id, name, serial, assignedRoomId, ip, mac, status, installedAt, updatedAt, data)
                    return {
                        "id": kiosk_id,
                        "name": name,
                        "serialNumber": serial,
                        "assignedRoomId": assignedRoomId,
                        "ipAddress": ip,
                        "macAddress": mac,
                        "status": status,
                        "installedAt": installedAt,
                        "updatedAt": updatedAt,
                    }
            except Exception:
                # Firestore query failed; fall back to creating local record
                pass

        # 3) Not found in Firestore or Firestore unavailable: create new kiosk id and persist
        kiosk_id = _next_kiosk_id(conn)
        name = hostname or kiosk_id
        installedAt = now
        updatedAt = now
        status = "online"

        # try to create Firestore doc with kiosk_id as doc id (best-effort)
        if db_fs:
            try:
                doc = {
                    "name": name,
                    "serialNumber": serial,
                    "assignedRoomId": None,
                    "ipAddress": None,
                    "macAddress": None,
                    "status": status,
                    "installedAt": installedAt,
                    "updatedAt": updatedAt,
                }
                db_fs.collection("kiosks").document(kiosk_id).set(doc)
            except Exception:
                # ignore Firestore write failures
                pass

        # persist locally into kiosks_fs
        try:
            _write_local_kiosk(conn, kiosk_id, name, serial, None, None, None, status, installedAt, updatedAt, {"auto_registered": True})
        except Exception:
            pass

        return {
            "id": kiosk_id,
            "name": name,
            "serialNumber": serial,
            "assignedRoomId": None,
            "ipAddress": None,
            "macAddress": None,
            "status": status,
            "installedAt": installedAt,
            "updatedAt": updatedAt,
        }
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return None


@router.post("/device/register")
def http_register_device():
    r = register_device_auto()
    if not r:
        return JSONResponse(content={"error": "failed"}, status_code=500)
    return {"status": "ok", "kiosk": r}


@router.post("/device/claim")
def http_claim_device(body: dict = None):
    """Manually bind this device (by serial or hostname) to an existing kiosk fs_id.

    Body: { fs_id: "kiosk-201" }
    This writes the current device serial (if present) into the kiosks_fs row with that fs_id.
    """
    try:
        # FastAPI will pass parsed JSON as body param if declared; fall back to reading from request if needed
        from fastapi import Request
        return JSONResponse(content={"error": "not_implemented"}, status_code=501)
    except Exception:
        return JSONResponse(content={"error": "failed"}, status_code=500)


@router.post("/device/network")
def http_update_network_info():
    """Detect local IP/MAC and persist into local kiosks_fs row and attempt to update Firestore kiosk doc.

    Returns: { kiosk: { ... } } similar to /device/info
    """
    try:
        serial = _read_rpi_serial()
        hostname = socket.gethostname()
        conn = state.get_db()
        _ensure_kiosk_table(conn)
        cur = conn.cursor()

        # detect network info locally
        ip = _detect_ip_address()
        mac = _detect_mac_address()
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")

        # try to find existing local kiosk row by serial
        row = None
        if serial:
            try:
                cur.execute("SELECT fs_id, name, serialNumber, assignedRoomId, ipAddress, macAddress, status, installedAt, updatedAt, raw_doc FROM kiosks_fs WHERE serialNumber = ?", (serial,))
                row = cur.fetchone()
            except Exception:
                row = None

        if not row:
            # fallback: try matching by hostname or first kiosk
            try:
                cur.execute("SELECT fs_id, name, serialNumber, assignedRoomId, ipAddress, macAddress, status, installedAt, updatedAt, raw_doc FROM kiosks_fs LIMIT 1")
                row = cur.fetchone()
            except Exception:
                row = None

        kiosk_id = None
        name = hostname
        assigned_room = None
        installedAt = now
        updatedAt = now
        status = "online"
        raw = None

        if row:
            kiosk_id = row[0]
            name = row[1] or name
            assigned_room = row[3]
            installedAt = row[7] or now
            updatedAt = now
            status = row[6] or status
            raw = row[9] if len(row) > 9 else None

        # persist locally (INSERT OR REPLACE)
        try:
            cur.execute(
                "INSERT OR REPLACE INTO kiosks_fs (fs_id, name, serialNumber, assignedRoomId, ipAddress, macAddress, status, installedAt, updatedAt, raw_doc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kiosk_id or _next_kiosk_id(conn), name, serial or "", assigned_room, ip, mac, status, installedAt, updatedAt, raw if raw is not None else None),
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

        # attempt to update Firestore kiosk doc if available
        db_fs = getattr(sync, "db_fs", None) if sync is not None else None
        if db_fs and kiosk_id:
            try:
                doc_ref = db_fs.collection("kiosks").document(kiosk_id)
                doc_ref.update({"ipAddress": ip, "macAddress": mac, "updatedAt": updatedAt})
            except Exception:
                # best-effort, ignore failures
                pass

        # return updated kiosk info
        try:
            cur.execute("SELECT fs_id, name, serialNumber, assignedRoomId, ipAddress, macAddress, status, installedAt, updatedAt FROM kiosks_fs WHERE fs_id = ?", (kiosk_id or None,))
            crow = cur.fetchone()
            if not crow:
                # try by serial
                cur.execute("SELECT fs_id, name, serialNumber, assignedRoomId, ipAddress, macAddress, status, installedAt, updatedAt FROM kiosks_fs WHERE serialNumber = ?", (serial,))
                crow = cur.fetchone()
        except Exception:
            crow = None

        if crow:
            return {"kiosk": {"id": crow[0], "name": crow[1], "serialNumber": crow[2], "assignedRoomId": crow[3], "assignedRoomName": None, "ipAddress": crow[4], "macAddress": crow[5], "status": crow[6], "installedAt": crow[7], "updatedAt": crow[8]}}
        return {"kiosk": None}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@router.get("/device/info")
def http_device_info():
    try:
        serial = _read_rpi_serial()
        if not serial:
            return {"kiosk": None}
        conn = state.get_db()
        _ensure_kiosk_table(conn)
        cur = conn.cursor()
        cur.execute("SELECT fs_id, name, serialNumber, assignedRoomId, ipAddress, macAddress, status, installedAt, updatedAt FROM kiosks_fs WHERE serialNumber = ?", (serial,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"kiosk": None}

        assigned_room_id = row[3]
        assigned_room_name = "Unavailable"
        # try to resolve assigned room name from rooms_fs table (populated by /sync)
        try:
            if assigned_room_id:
                cur.execute("SELECT roomname FROM rooms_fs WHERE fs_id = ?", (assigned_room_id,))
                rr = cur.fetchone()
                if rr and rr[0]:
                    assigned_room_name = rr[0]
        except Exception:
            # if rooms_fs table doesn't exist or query fails, leave as Not Assigned
            assigned_room_name = "Unavailable"

        conn.close()
        return {
            "kiosk": {
                "id": row[0],
                "name": row[1],
                "serialNumber": row[2],
                "assignedRoomId": assigned_room_id,
                "assignedRoomName": assigned_room_name,
                "ipAddress": row[4],
                "macAddress": row[5],
                "status": row[6],
                "installedAt": row[7],
                "updatedAt": row[8],
            }
        }
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
