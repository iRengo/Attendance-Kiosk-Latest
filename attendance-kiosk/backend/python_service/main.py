from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio

# Use FastAPI lifespan instead of the removed on_event decorator.
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic (migrated from on_event startup)
    try:
        # Ensure DB and schema exist early (creates kiosk_notifications etc.)
        try:
            state.get_db()
        except Exception:
            pass
        # load embeddings after ensuring DB/schema
        try:
            state.load_embeddings()
        except Exception:
            pass
    except Exception:
        pass

    # Run the remainder of the original startup code in an executor to
    # avoid blocking the event loop. These operations are best-effort and
    # may perform network I/O / DB access.
    def _startup_tasks():
        try:
            # First try to sync Firestore into the local DB so rooms/kiosks are fresh
            try:
                res = sync.sync_firestore()
                try:
                    if isinstance(res, dict) and res.get('status') == 'success':
                        try:
                            from api import kiosk_notifications as kn
                            kiosk_id_local = None
                            room_id_local = None
                            try:
                                conn_loc = state.get_db()
                                cur_loc = conn_loc.cursor()
                                try:
                                    cur_loc.execute("SELECT fs_id, assignedRoomId FROM kiosks_fs LIMIT 1")
                                    r = cur_loc.fetchone()
                                    if r:
                                        kiosk_id_local = r[0]
                                        room_id_local = r[1]
                                except Exception:
                                    try:
                                        cur_loc.execute("SELECT fs_id FROM kiosks_fs LIMIT 1")
                                        r = cur_loc.fetchone()
                                        if r:
                                            kiosk_id_local = r[0]
                                    except Exception:
                                        pass
                                try:
                                    conn_loc.close()
                                except Exception:
                                    pass
                            except Exception:
                                pass

                            try:
                                if not kiosk_id_local:
                                    try:
                                        devinfo = device.register_device_auto()
                                        if devinfo:
                                            kiosk_id_local = devinfo.get('id') or devinfo.get('fs_id')
                                            room_id_local = devinfo.get('assignedRoomId') or devinfo.get('assignedRoom') or room_id_local
                                    except Exception:
                                        try:
                                            dinfo = device.http_device_info()
                                            if dinfo and dinfo.get('kiosk'):
                                                kk = dinfo.get('kiosk')
                                                kiosk_id_local = kk.get('id') or kiosk_id_local
                                                room_id_local = kk.get('assignedRoomId') or room_id_local
                                        except Exception:
                                            pass
                            except Exception:
                                pass

                            try:
                                msg_ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                                kn.insert_local_and_maybe_remote({
                                    'notif_id': f'startup-sync-success-{int(time.time())}',
                                    'kiosk_id': kiosk_id_local,
                                    'room': room_id_local,
                                    'title': 'Sync completed',
                                    'type': 'info',
                                    'details': f'syncing was completed at {msg_ts}',
                                    'timestamp': msg_ts,
                                    'createdAt': msg_ts,
                                })
                            except Exception:
                                pass
                        except Exception:
                            pass
                except Exception:
                    pass
            except Exception:
                try:
                    from api import kiosk_notifications as kn
                    kiosk_id_local = None
                    room_id_local = None
                    try:
                        conn_loc = state.get_db()
                        cur_loc = conn_loc.cursor()
                        try:
                            cur_loc.execute("SELECT fs_id, assignedRoomId FROM kiosks_fs LIMIT 1")
                            r = cur_loc.fetchone()
                            if r:
                                kiosk_id_local = r[0]
                                room_id_local = r[1]
                        except Exception:
                            try:
                                cur_loc.execute("SELECT fs_id FROM kiosks_fs LIMIT 1")
                                r = cur_loc.fetchone()
                                if r:
                                    kiosk_id_local = r[0]
                            except Exception:
                                pass
                        try:
                            conn_loc.close()
                        except Exception:
                            pass
                    except Exception:
                        pass

                    kn.insert_local_and_maybe_remote({
                        'notif_id': f'startup-sync-failed-{int(time.time())}',
                        'kiosk_id': kiosk_id_local,
                        'room': room_id_local,
                        'title': 'Startup sync failed',
                        'type': 'warning',
                        'details': {'reason': 'firestore_unavailable'},
                        'timestamp': time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        'createdAt': time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    })
                except Exception:
                    pass

            try:
                device.register_device_auto()
            except Exception:
                pass
        except Exception:
            pass

    # Run startup tasks without blocking the event loop
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _startup_tasks)
    except Exception:
        # if no running loop or executor fails, try direct call
        try:
            _startup_tasks()
        except Exception:
            pass

    # Start partial background sync (lightweight) so target tables are kept up-to-date
    try:
        try:
            sync.start_partial_background_sync()
        except Exception:
            pass
    except Exception:
        pass

    yield

    # Shutdown logic (migrated from on_event shutdown)
    try:
        # no background sync thread to stop
        pass
    except Exception:
        pass

# Small app that composes routers from the api package
app = FastAPI(title="Offline Kiosk Face Recognition", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and include routers from the api package
from api import state, recognition, sync, session, outbox, media, students, registry, device, teachers, kiosk_notifications, monitor
import threading
import os
import time
import subprocess

app.include_router(recognition.router)
app.include_router(sync.router)
app.include_router(session.router)
app.include_router(outbox.router)
app.include_router(media.router)
app.include_router(students.router)
app.include_router(teachers.router)
app.include_router(registry.router)
app.include_router(device.router)
app.include_router(kiosk_notifications.router)
app.include_router(monitor.router)


@app.get("/health")
def health_check():
    return {"ok": True}


