# Manual test checklist

Things that need real hardware (Pi + SuperDrive + hub) and can't be unit
tested. Run through this before tagging a release once the relevant
phases land — empty for now since Phase 0 has no hardware-touching code
yet.

## Drive control (Phase 2+)
- [ ] Wake-up SCSI command runs successfully before a scan
- [ ] Eject step 1 (`eject -f`) works on a normal disc
- [ ] Eject step 2 (SCSI eject) works when step 1 fails
- [ ] Eject step 3 (USB unbind/rebind) clears a stuck disc
- [ ] Card reader (`sda`/`sdb`) is never mistaken for the optical drive

## Ripping (Phase 3+)
- [ ] DVD scan correctly identifies the "Main Feature" title
- [ ] Rip completes and lands at the correct Plex path
- [ ] Destination folder is owned by `pauls:pauls`, not root
- [ ] Progress bar/percent roughly tracks real HandBrake progress

## Resilience (Phase 1+)
- [ ] Closing the browser tab mid-rip doesn't kill the job
- [ ] Reloading the page mid-rip shows the current job status
- [ ] A dropped WiFi connection doesn't crash the backend
