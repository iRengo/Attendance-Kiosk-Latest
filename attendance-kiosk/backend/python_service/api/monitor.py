import threading
import time
import subprocess
import requests
import time as _time
import os
from fastapi import APIRouter

from . import state

router = APIRouter()

# Public status object updated by the monitor loop
status = {
    "online": None,
    "undervolt": None,
    "temp_c": None,
    "hot": None,
    "last_checked": None,
}


def _get_local_kiosk_and_room():
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
    # If kiosks_fs did not return any value, attempt to use device.register_device_auto to populate local kiosk info
    if not kiosk_id_local:
        try:
            from . import device
            dev = device.register_device_auto()
            if dev:
                kiosk_id_local = dev.get('id') or dev.get('fs_id')
                room_id_local = dev.get('assignedRoomId') or dev.get('assignedRoom') or room_id_local
        except Exception:
            try:
                # as a fallback, call device.info endpoint
                from . import device
                di = device.http_device_info()
                if di and di.get('kiosk'):
                    kk = di.get('kiosk')
                    kiosk_id_local = kk.get('id') or kiosk_id_local
                    room_id_local = kk.get('assignedRoomId') or room_id_local
            except Exception:
                pass
    return kiosk_id_local, room_id_local


def _check_internet(timeout=2.0):
    """Return True if a simple HTTP request indicates internet connectivity."""
    try:
        # lightweight endpoint that returns 204 on success (prefer HTTPS)
        try:
            r = requests.get("https://clients3.google.com/generate_204", timeout=timeout)
            if r.status_code == 204 or (200 <= r.status_code < 400):
                return True
        except Exception:
            # try HTTP as a fallback
            try:
                r = requests.get("http://clients3.google.com/generate_204", timeout=timeout)
                if r.status_code == 204 or (200 <= r.status_code < 400):
                    return True
            except Exception:
                pass
        # fallback: attempt a lightweight socket connect to a public DNS (port 53)
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect(("8.8.8.8", 53))
            s.close()
            return True
        except Exception:
            return False
    except Exception:
        return False


def _check_undervolt():
    try:
        p = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2)
        out = p.stdout.strip()
        if 'throttled=' in out:
            hx = out.split('throttled=')[-1].strip()
            try:
                val = int(hx, 16)
                undervolt = (val & 0x1) != 0
                return undervolt
            except Exception:
                return False
        return False
    except Exception:
        return False


def _check_temp():
    """Return temperature in Celsius as float, or None if unavailable."""
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            val = f.read().strip()
            if val:
                return int(val) / 1000.0
    except Exception:
        pass
    return None


def _monitor_loop():
    try:
        from . import kiosk_notifications as kn
    except Exception:
        kn = None

    was_online = None
    was_undervolt = None
    was_hot = None

    # Run an immediate one-shot health check at thread start so operators
    # see startup conditions (overheat, low-voltage, no-internet) without
    # waiting for the first periodic interval.
    try:
        try:
            online = _check_internet()
        except Exception:
            online = False
        try:
            undervolt = _check_undervolt()
        except Exception:
            undervolt = False
        try:
            temp_c = _check_temp()
        except Exception:
            temp_c = None

        HOT_C_THRESHOLD = float(os.environ.get('HOT_C_THRESHOLD', '75'))
        hot = (temp_c is not None and temp_c >= HOT_C_THRESHOLD)

        # update public status immediately
        try:
            status["online"] = online
            status["undervolt"] = undervolt
            status["temp_c"] = temp_c
            status["hot"] = hot
            status["last_checked"] = _time.strftime("%Y-%m-%dT%H:%M:%S%z")
        except Exception:
            pass

        # emit startup notifications for current problematic conditions
        if kn:
            kiosk_id_local, room_id_local = _get_local_kiosk_and_room()
            ts = _time.strftime("%Y-%m-%dT%H:%M:%S%z")
            try:
                if hot:
                    kn.insert_local_and_maybe_remote({
                        'notif_id': f'startup-device-hot-{int(time.time())}',
                        'kiosk_id': kiosk_id_local,
                        'room': room_id_local,
                        'title': 'Device overheating',
                        'type': 'warning',
                        'details': f'Device overheating detected at startup {ts}',
                        'timestamp': ts,
                        'createdAt': ts,
                    })
            except Exception:
                pass
            try:
                if undervolt:
                    kn.insert_local_and_maybe_remote({
                        'notif_id': f'startup-low-voltage-{int(time.time())}',
                        'kiosk_id': kiosk_id_local,
                        'room': room_id_local,
                        'title': 'Low voltage detected',
                        'type': 'warning',
                        'details': f'Low voltage detected at startup {ts}',
                        'timestamp': ts,
                        'createdAt': ts,
                    })
            except Exception:
                pass
            try:
                if not online:
                    kn.insert_local_and_maybe_remote({
                        'notif_id': f'startup-internet-lost-{int(time.time())}',
                        'kiosk_id': kiosk_id_local,
                        'room': room_id_local,
                        'title': 'Internet connection lost',
                        'type': 'alert',
                        'details': f'No internet connectivity detected at startup {ts}',
                        'timestamp': ts,
                        'createdAt': ts,
                    })
            except Exception:
                pass

            # If we have internet at startup, attempt a sync to pull remote notifications
            # into the local DB immediately (best-effort).
            try:
                if online:
                    from . import sync
                    try:
                        res = sync.sync_firestore()
                        # If sync succeeded at startup, skip creating a duplicate startup-sync notification here.
                        # Other monitor/device notifications will cover sync status transitions.
                        pass
                    except Exception:
                        pass
            except Exception:
                pass

        # prime the previous-state variables so the regular loop treats the
        # next transitions as changes from this baseline rather than from None.
        was_online = online
        was_undervolt = undervolt
        was_hot = hot
    except Exception:
        # ignore any errors in the startup check to avoid stopping the monitor
        pass

    while True:
        try:
            online = _check_internet()
        except Exception:
            online = False

        try:
            undervolt = _check_undervolt()
        except Exception:
            undervolt = False

        # update public status
        try:
            status["online"] = online
            status["undervolt"] = undervolt
            status["temp_c"] = None
            status["hot"] = None
            status["last_checked"] = _time.strftime("%Y-%m-%dT%H:%M:%S%z")

            # periodic temperature check (Raspberry Pi)
            try:
                temp_c = _check_temp()
                if temp_c is not None:
                    status["temp_c"] = temp_c
                    HOT_C_THRESHOLD = float(os.environ.get('HOT_C_THRESHOLD', '75'))
                    hot = temp_c >= HOT_C_THRESHOLD
                    status["hot"] = hot
                else:
                    temp_c = None
                    hot = None
            except Exception:
                temp_c = None
                hot = None

            # initialize previous state on first run
            if was_online is None:
                was_online = online
            if was_undervolt is None:
                was_undervolt = undervolt
            if was_hot is None:
                was_hot = hot

            # temperature transitions
            try:
                if was_hot is False and hot is True:
                    # overheating detected -> WARN
                    if kn:
                        kiosk_id_local, room_id_local = _get_local_kiosk_and_room()
                        ts = _time.strftime("%Y-%m-%dT%H:%M:%S%z")
                        try:
                            kn.insert_local_and_maybe_remote({
                                'notif_id': f'device-hot-{int(time.time())}',
                                'kiosk_id': kiosk_id_local,
                                'room': room_id_local,
                                'title': 'Device overheating',
                                'type': 'warning',
                                'details': f'Device overheating detected at {ts}',
                                'timestamp': ts,
                                'createdAt': ts,
                            })
                        except Exception:
                            pass
                if was_hot is True and hot is False:
                    # temperature normalized -> success
                    if kn:
                        kiosk_id_local, room_id_local = _get_local_kiosk_and_room()
                        ts = _time.strftime("%Y-%m-%dT%H:%M:%S%z")
                        try:
                            kn.insert_local_and_maybe_remote({
                                'notif_id': f'device-temp-normal-{int(time.time())}',
                                'kiosk_id': kiosk_id_local,
                                'room': room_id_local,
                                'title': 'Device temperature normalized',
                                'type': 'success',
                                'details': f'Device temperature normalized at {ts}',
                                'timestamp': ts,
                                'createdAt': ts,
                            })
                        except Exception:
                            pass
            except Exception:
                pass
            was_hot = hot

            # network transitions
            try:
                if was_online is False and online is True:
                    # internet restored -> success
                    if kn:
                        kiosk_id_local, room_id_local = _get_local_kiosk_and_room()
                        ts = _time.strftime("%Y-%m-%dT%H:%M:%S%z")
                        try:
                            kn.insert_local_and_maybe_remote({
                                'notif_id': f'internet-restored-{int(time.time())}',
                                'kiosk_id': kiosk_id_local,
                                'room': room_id_local,
                                'title': 'Internet restored',
                                'type': 'success',
                                'details': f'internet restored was a success at {ts}',
                                'timestamp': ts,
                                'createdAt': ts,
                            })
                        except Exception:
                            pass
                    # attempt to run a full sync to pull remote notifications into local DB
                    try:
                        from . import sync
                        try:
                            res = sync.sync_firestore()
                            # if sync reports success, create an info notification
                            try:
                                if isinstance(res, dict) and res.get('status') == 'success':
                                    try:
                                        ts2 = _time.strftime("%Y-%m-%dT%H:%M:%S%z")
                                        kn.insert_local_and_maybe_remote({
                                            'notif_id': f'sync-completed-{int(time.time())}',
                                            'kiosk_id': kiosk_id_local,
                                            'room': room_id_local,
                                            'title': 'Sync completed',
                                            'type': 'info',
                                            'details': f'syncing was completed at {ts2}',
                                            'timestamp': ts2,
                                            'createdAt': ts2,
                                        })
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                        except Exception:
                            pass
                    except Exception:
                        pass
                if was_online is True and online is False:
                    # internet lost -> alert
                    if kn:
                        kiosk_id_local, room_id_local = _get_local_kiosk_and_room()
                        ts = _time.strftime("%Y-%m-%dT%H:%M:%S%z")
                        try:
                            kn.insert_local_and_maybe_remote({
                                'notif_id': f'internet-lost-{int(time.time())}',
                                'kiosk_id': kiosk_id_local,
                                'room': room_id_local,
                                'title': 'Internet connection lost',
                                'type': 'alert',
                                'details': f'internet connection lost at {ts}',
                                'timestamp': ts,
                                'createdAt': ts,
                            })
                        except Exception:
                            pass
            except Exception:
                pass
            was_online = online

            # undervolt transitions
            try:
                if was_undervolt is False and undervolt is True:
                    # undervolt detected -> warning
                    if kn:
                        kiosk_id_local, room_id_local = _get_local_kiosk_and_room()
                        ts = _time.strftime("%Y-%m-%dT%H:%M:%S%z")
                        try:
                            kn.insert_local_and_maybe_remote({
                                'notif_id': f'low-voltage-{int(time.time())}',
                                'kiosk_id': kiosk_id_local,
                                'room': room_id_local,
                                'title': 'Low voltage detected',
                                'type': 'warning',
                                'details': f'Low voltage detected at {ts}',
                                'timestamp': ts,
                                'createdAt': ts,
                            })
                        except Exception:
                            pass
                if was_undervolt is True and undervolt is False:
                    # undervolt restored -> success
                    if kn:
                        kiosk_id_local, room_id_local = _get_local_kiosk_and_room()
                        ts = _time.strftime("%Y-%m-%dT%H:%M:%S%z")
                        try:
                            kn.insert_local_and_maybe_remote({
                                'notif_id': f'low-voltage-restored-{int(time.time())}',
                                'kiosk_id': kiosk_id_local,
                                'room': room_id_local,
                                'title': 'Low voltage restored',
                                'type': 'success',
                                'details': f'Low voltage condition cleared at {ts}',
                                'timestamp': ts,
                                'createdAt': ts,
                            })
                        except Exception:
                            pass
            except Exception:
                pass

        except Exception:
            # swallow any transient errors in the monitor loop to keep it running
            pass

        time.sleep(15)


try:
    t = threading.Thread(target=_monitor_loop, daemon=True)
    t.start()
except Exception:
    pass


@router.get('/monitor/status')
def get_monitor_status():
    try:
        return {"status": status}
    except Exception:
        return {"status": "error"}
