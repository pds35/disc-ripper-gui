/* ============================================================
   Disc Ripper GUI - dashboard frontend logic.
   Phase 5.

   Plain JS, no framework/build step - matches the project's "clear,
   well-commented code over cleverness" goal for a learning project.
   Polls the backend every 2 seconds rather than using websockets -
   simpler to reason about, and fine for a single-user dashboard.
   ============================================================ */

const POLL_INTERVAL_MS = 2000;

/**
 * Turn a number of seconds into a short "Hh Mm Ss" style string.
 * Returns "--" for null/undefined, since the backend sends null
 * when there's no meaningful ETA/duration yet.
 */
function formatDuration(totalSeconds) {
  if (totalSeconds === null || totalSeconds === undefined) {
    return "--";
  }
  const seconds = Math.round(totalSeconds);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;

  if (hours > 0) {
    return hours + "h " + minutes + "m " + secs + "s";
  }
  if (minutes > 0) {
    return minutes + "m " + secs + "s";
  }
  return secs + "s";
}

/**
 * Update the current-job card and header LED from a /api/jobs/status
 * response.
 */
function updateJobUI(job) {
  const titleEl = document.getElementById("job-title");
  const fillEl = document.getElementById("progress-fill");
  const percentEl = document.getElementById("progress-percent");
  const etaEl = document.getElementById("job-eta");
  const rateEl = document.getElementById("job-rate");
  const ledDotEl = document.getElementById("drive-led-dot");
  const ledLabelEl = document.getElementById("drive-led-label");
  const ejectBtn = document.getElementById("eject-btn");

  if (job.state === "running") {
    const title = job.movie_title
      ? job.movie_title + (job.movie_year ? " (" + job.movie_year + ")" : "")
      : "Ripping...";
    titleEl.textContent = title;

    const percent = job.percent || 0;
    fillEl.style.width = percent + "%";
    fillEl.classList.remove("level-meter__fill--done");
    percentEl.textContent = percent.toFixed(1) + "%";
    etaEl.textContent = "ETA " + formatDuration(job.eta_seconds);
    rateEl.textContent = job.rate_fps ? job.rate_fps.toFixed(1) + " fps" : "-- fps";

    ledDotEl.className = "drive-led__dot drive-led__dot--busy";
    ledLabelEl.textContent = "DRIVE: BUSY";
    ejectBtn.disabled = true;
  } else if (job.state === "done") {
    const title = job.movie_title
      ? job.movie_title + (job.movie_year ? " (" + job.movie_year + ")" : "")
      : "Last rip";
    titleEl.textContent = title + " - done";
    fillEl.style.width = "100%";
    fillEl.classList.add("level-meter__fill--done");
    percentEl.textContent = "100%";
    etaEl.textContent = "ETA --";
    rateEl.textContent = "-- fps";

    ledDotEl.className = "drive-led__dot drive-led__dot--idle";
    ledLabelEl.textContent = "DRIVE: IDLE";
    ejectBtn.disabled = false;
  } else if (job.state === "error") {
    titleEl.textContent = "Last rip failed";
    ledDotEl.className = "drive-led__dot drive-led__dot--error";
    ledLabelEl.textContent = "DRIVE: ERROR";
    ejectBtn.disabled = false;
  } else {
    titleEl.textContent = "No job running";
    fillEl.style.width = "0%";
    fillEl.classList.remove("level-meter__fill--done");
    percentEl.textContent = "--%";
    etaEl.textContent = "ETA --";
    rateEl.textContent = "-- fps";

    ledDotEl.className = "drive-led__dot drive-led__dot--idle";
    ledLabelEl.textContent = "DRIVE: IDLE";
    ejectBtn.disabled = false;
  }
}

/**
 * Update the quick-stats tiles and recent-activity list from a
 * /api/stats response.
 */
function updateStatsUI(stats) {
  document.getElementById("stat-drive-status").textContent = stats.drive_status;
  document.getElementById("stat-ripped-today").textContent = stats.discs_ripped_today;
  document.getElementById("stat-free-space").textContent =
    stats.free_space_gb !== null ? stats.free_space_gb + " GB" : "--";

  const listEl = document.getElementById("activity-list");

  if (!stats.recent_activity || stats.recent_activity.length === 0) {
    listEl.innerHTML = '<li class="activity-list__empty">No rips yet</li>';
    return;
  }

  listEl.innerHTML = "";
  for (const entry of stats.recent_activity) {
    const li = document.createElement("li");

    const nameSpan = document.createElement("span");
    const title = entry.movie_title || "Untitled rip";
    const year = entry.movie_year ? " (" + entry.movie_year + ")" : "";
    nameSpan.textContent = title + year;

    const durationSpan = document.createElement("span");
    durationSpan.className = "activity-list__duration";
    durationSpan.textContent = formatDuration(entry.duration_seconds);

    li.appendChild(nameSpan);
    li.appendChild(durationSpan);
    listEl.appendChild(li);
  }
}

/**
 * Fetch both job status and stats, update the whole UI. Called on
 * page load and then every POLL_INTERVAL_MS.
 */
async function refreshDashboard() {
  try {
    const [jobRes, statsRes] = await Promise.all([
      fetch("/api/jobs/status"),
      fetch("/api/stats"),
    ]);
    const job = await jobRes.json();
    const stats = await statsRes.json();
    updateJobUI(job);
    updateStatsUI(stats);
  } catch (err) {
    // Network hiccups happen on this WiFi (see project brief) - fail
    // quietly and just try again on the next poll rather than
    // breaking the whole page.
    console.error("Dashboard refresh failed:", err);
  }
}

function showDriveMessage(text) {
  document.getElementById("drive-message").textContent = text;
}

async function handleWake() {
  const btn = document.getElementById("wake-btn");
  btn.disabled = true;
  showDriveMessage("Waking drive...");
  try {
    const res = await fetch("/api/drive/wake", { method: "POST" });
    const data = await res.json();
    showDriveMessage(data.success ? "Drive woken." : "Wake failed: " + data.output);
  } catch (err) {
    showDriveMessage("Wake request failed - check connection.");
  }
  btn.disabled = false;
}

async function handleEject() {
  const btn = document.getElementById("eject-btn");
  btn.disabled = true;
  showDriveMessage("Ejecting...");
  try {
    const res = await fetch("/api/drive/eject", { method: "POST" });
    const data = await res.json();
    if (res.status === 409) {
      showDriveMessage("Can't eject - a rip is currently running.");
    } else if (data.success) {
      showDriveMessage("Ejected (" + data.worked_step + ").");
    } else {
      showDriveMessage("Eject failed after trying all steps.");
    }
  } catch (err) {
    showDriveMessage("Eject request failed - check connection.");
  }
  btn.disabled = false;
}

document.getElementById("wake-btn").addEventListener("click", handleWake);
document.getElementById("eject-btn").addEventListener("click", handleEject);

refreshDashboard();
setInterval(refreshDashboard, POLL_INTERVAL_MS);

/* ---- Scan disc / start new rip ---- */

let scannedHandbrakeTitle = null;

function populateTrackSelect(selectEl, tracks, includeNoneOption) {
  selectEl.innerHTML = "";
  if (includeNoneOption) {
    const noneOpt = document.createElement("option");
    noneOpt.value = "";
    noneOpt.textContent = "None";
    selectEl.appendChild(noneOpt);
  }
  for (const track of tracks) {
    const opt = document.createElement("option");
    opt.value = track.track_number;
    opt.textContent = "Track " + track.track_number + " - " + track.language;
    selectEl.appendChild(opt);
  }
}

async function handleScan() {
  const btn = document.getElementById("scan-btn");
  const scanMessage = document.getElementById("scan-message");
  const scanResult = document.getElementById("scan-result");

  btn.disabled = true;
  scanResult.style.display = "none";
  scanMessage.textContent = "Scanning disc - this can take up to a minute...";

  try {
    const res = await fetch("/api/scan", { method: "POST" });
    const data = await res.json();

    if (!data.success) {
      scanMessage.textContent = "Scan failed: " + data.error;
      btn.disabled = false;
      return;
    }

    scannedHandbrakeTitle = data.index;
    document.getElementById("scan-summary").textContent =
      "Main feature: " + data.duration_display + " (" + data.title_count + " titles on disc)";

    populateTrackSelect(document.getElementById("audio-track-select"), data.audio_tracks, false);
    populateTrackSelect(document.getElementById("sub-track-select"), data.subtitle_tracks, true);

    scanResult.style.display = "block";
    scanMessage.textContent = "";
  } catch (err) {
    scanMessage.textContent = "Scan request failed - check connection.";
  }
  btn.disabled = false;
}

async function handleStartRip() {
  const btn = document.getElementById("start-rip-btn");
  const scanMessage = document.getElementById("scan-message");

  const title = document.getElementById("movie-title-input").value.trim();
  const year = document.getElementById("movie-year-input").value;
  const audioTrack = document.getElementById("audio-track-select").value;
  const subTrack = document.getElementById("sub-track-select").value;

  if (!title || !year || !audioTrack) {
    scanMessage.textContent = "Movie title, year, and audio track are required.";
    return;
  }

  btn.disabled = true;
  scanMessage.textContent = "Starting rip...";

  try {
    const res = await fetch("/api/rip/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: title,
        year: parseInt(year, 10),
        handbrake_title: scannedHandbrakeTitle,
        audio_track: parseInt(audioTrack, 10),
        sub_track: subTrack ? parseInt(subTrack, 10) : null,
      }),
    });
    const data = await res.json();

    if (res.status === 202) {
      scanMessage.textContent = "Rip started: " + data.output_path;
      document.getElementById("scan-result").style.display = "none";
      refreshDashboard();
    } else {
      scanMessage.textContent = "Could not start rip: " + data.error;
    }
  } catch (err) {
    scanMessage.textContent = "Start rip request failed - check connection.";
  }
  btn.disabled = false;
}

document.getElementById("scan-btn").addEventListener("click", handleScan);
document.getElementById("start-rip-btn").addEventListener("click", handleStartRip);
