"""
Drive control: wake-up and eject for the Apple USB SuperDrive.

Phase 2 goal: expose the manually-proven wake/eject commands (see the
project brief) as functions the Flask routes can call, with eject's
multi-step fallback chain surfaced as structured results rather than a
single pass/fail.

Design decisions:

- All commands here need `sudo` (sg_raw, eject, and the USB
  unbind/rebind under /sys/bus/usb/drivers/usb/). Since this runs from
  a background web server, not an interactive terminal, sudo can't
  prompt for a password. This means passwordless sudo needs to be
  configured for these SPECIFIC commands (not blanket NOPASSWD) via
  `sudo visudo` — see README for the exact sudoers lines. Until that's
  set up, these calls will hang or fail waiting on a password prompt
  that never comes. This is a real setup step, not optional.
- Eject fallback chain order was REVISED after testing against real
  hardware — see DEVLOG for the full story. The brief's original chain
  (soft eject -> SCSI eject -> USB reset) was based on manual testing
  where the USB unbind/rebind appeared to work. Root-caused it further:
  the actual blocker was the drive's SCSI "prevent medium removal" flag
  (likely being set by udisks2, since the Pi runs a desktop
  environment) — confirmed via the sense error "Medium removal
  prevented". The USB reset was only *appearing* to work in past manual
  sessions coincidentally. The real fix is sending an explicit SCSI
  ALLOW MEDIUM REMOVAL command immediately before the SCSI eject, which
  reliably clears the lock. New order: allow-removal+SCSI eject first
  (fast, no USB reset needed), soft eject second, full USB reset kept
  only as a genuine last resort for a truly wedged drive.
- The USB unbind/rebind reset does NOT by itself physically open the
  tray (confirmed via testing) — it only clears the drive's stuck
  busy/locked state. A follow-up eject command is required after the
  device node reappears; that retry's result, not the reset's exit
  code, is what determines success for that step.
- The USB port path ("1-2.3") is hardcoded per the brief, but the brief
  itself flags this needs reconfirming with `lsusb | grep -i apple` —
  it can change if the hub is plugged into a different port. Pulled out
  as a constant at the top of this file so it's a one-line fix if it
  ever changes, not a hunt through the code.
- Every subprocess call uses a timeout. A hung `sg_raw` call (drive not
  responding) would otherwise block the calling thread indefinitely —
  bad news for a request that's supposed to return quickly.
"""

import subprocess
import time
import os

DRIVE_DEVICE = "/dev/sr0"

# From the project brief — confirm with `lsusb | grep -i apple` if the
# hub's physical port ever changes.
USB_PORT_PATH = "1-2.3"

# Seconds to wait before giving up on any single drive command.
COMMAND_TIMEOUT = 15


def _run(command, timeout=COMMAND_TIMEOUT):
    """
    Run a command, capturing output. Returns (success, output) rather
    than raising, so callers can build structured API responses instead
    of catching exceptions everywhere.
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except FileNotFoundError as e:
        return False, f"command not found: {e}"


def wake_drive():
    """
    Send the wake-up SCSI command. Must run before any scan/rip, per
    the brief — the SuperDrive won't read a disc otherwise.

    Returns a dict: {"success": bool, "output": str}
    """
    success, output = _run(
        ["sudo", "sg_raw", DRIVE_DEVICE, "EA", "00", "00", "00", "00", "00", "01"]
    )
    return {"success": success, "output": output}


def eject_drive():
    """
    Try the eject fallback chain, stopping at the first step that
    succeeds. Returns a dict describing what was tried and what
    (if anything) worked:

        {
            "success": bool,
            "worked_step": str | None,   # which step succeeded
            "attempts": [                 # every step tried, in order
                {"step": str, "success": bool, "output": str},
                ...
            ],
        }
    """
    steps = [
        ("allow_removal_scsi_eject", _try_allow_removal_and_scsi_eject),
        ("soft_eject", _try_soft_eject),
        ("usb_reset", _try_usb_reset),
    ]

    attempts = []
    for step_name, step_fn in steps:
        success, output = step_fn()
        attempts.append({"step": step_name, "success": success, "output": output})
        if success:
            return {"success": True, "worked_step": step_name, "attempts": attempts}

    # All three steps failed.
    return {"success": False, "worked_step": None, "attempts": attempts}


def _try_allow_removal_and_scsi_eject():
    """
    Step 1 (primary path, confirmed against real hardware): first send
    SCSI ALLOW MEDIUM REMOVAL, then the SCSI eject command.

    This was the actual fix discovered during testing — the drive kept
    refusing to eject with sense error "Medium removal prevented",
    something (likely udisks2, since this Pi runs a desktop
    environment) keeps setting the drive's removal-lock flag. Sending
    ALLOW MEDIUM REMOVAL immediately before the eject clears that lock
    just in time. Both commands need to happen back-to-back — the lock
    can get re-set again given enough time, so there's no advantage to
    separating them.
    """
    allow_ok, allow_output = _run(
        ["sudo", "sg_raw", DRIVE_DEVICE, "1E", "00", "00", "00", "00", "00"]
    )
    eject_ok, eject_output = _run(
        ["sudo", "sg_raw", DRIVE_DEVICE, "1B", "00", "00", "00", "02", "00"]
    )
    combined_output = f"allow_removal: {allow_output} | eject: {eject_output}"
    return eject_ok, combined_output


def _try_soft_eject():
    """Step 2 (backup): sync, then standard forced eject. Rarely needed
    now that step 1 handles the actual root cause, but kept as a cheap
    fallback in case the allow-removal command itself fails for some
    reason."""
    subprocess.run(["sync"], timeout=COMMAND_TIMEOUT)
    return _run(["sudo", "eject", "-f", DRIVE_DEVICE])


def _wait_for_device(timeout=10):
    """
    Poll for the device node to reappear after a USB unbind/rebind.
    The kernel takes a moment to re-enumerate the device; trying to
    eject before it's back would just fail again.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(DRIVE_DEVICE):
            return True
        time.sleep(0.5)
    return False


def _try_usb_reset():
    """
    Step 3 (last resort): unbind and rebind the USB device.

    Important finding from testing against real hardware: the reset
    alone does NOT physically open the tray. What it does is clear the
    drive's stuck "busy"/removal-locked state (confirmed: eject failed
    with "Device or resource busy" / "Medium removal prevented" before
    the reset). The tray only actually opens if we send a follow-up
    eject command once the device node reappears. Originally this
    function treated a successful unbind+rebind as "success" — that
    was wrong; it left the disc sitting un-ejected while reporting
    success. Fixed to retry the eject after the reset and use THAT
    result to determine success.
    """
    unbind_result = subprocess.run(
        ["sudo", "tee", "/sys/bus/usb/drivers/usb/unbind"],
        input=USB_PORT_PATH,
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT,
    )
    unbind_ok = unbind_result.returncode == 0

    time.sleep(3)  # matches the brief's manual fallback timing

    bind_result = subprocess.run(
        ["sudo", "tee", "/sys/bus/usb/drivers/usb/bind"],
        input=USB_PORT_PATH,
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT,
    )
    bind_ok = bind_result.returncode == 0

    reset_output = (
        f"unbind: {unbind_result.stdout}{unbind_result.stderr} "
        f"bind: {bind_result.stdout}{bind_result.stderr}"
    ).strip()

    if not (unbind_ok and bind_ok):
        return False, reset_output

    if not _wait_for_device(timeout=10):
        return False, f"{reset_output} | device node did not reappear within 10s"

    # Device is back. The busy/lock condition that blocked eject before
    # should now be cleared by the reset — retry the eject for real.
    retry_ok, retry_output = _run(["sudo", "eject", "-f", DRIVE_DEVICE])
    combined_output = f"{reset_output} | post-reset eject: {retry_output}"
    return retry_ok, combined_output
