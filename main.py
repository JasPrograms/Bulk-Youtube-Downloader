import sys, shutil
from pathlib import Path
import os
from typing import Optional, List, Dict, Any
from PySide6 import QtCore, QtGui, QtWidgets
from datetime import datetime

try:
    import yt_dlp
except ImportError:
    QtWidgets.QMessageBox.critical(None, "Missing dependency", "Install yt-dlp:\npy -m pip install yt-dlp")
    raise

APP_NAME = "YT Bulk Downloader"
ORG_NAME = "LocalTools"

def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None

def get_resource_path(relative_path: str) -> str:
    """Get the absolute path to a resource, works for dev and for PyInstaller."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def build_format(max_res: Optional[int]) -> str:
    # best video + best audio, optional cap
    return f"bv*[height<={max_res}]+ba/b[height<={max_res}]" if max_res else "bv*+ba/b"

def human_bytes(n: Optional[float]) -> str:
    if not n or n <= 0: return "0 B"
    units = ["B","KB","MB","GB","TB"]; i = 0
    while n >= 1024 and i < len(units)-1: n/=1024; i+=1
    return f"{n:.1f} {units[i]}"

class DLWorker(QtCore.QThread):
    sig_update = QtCore.Signal(int, dict)
    sig_done = QtCore.Signal()

    def __init__(self, rows: List[Dict[str, Any]], opts: Dict[str, Any]):
        super().__init__()
        self.rows = rows
        self.opts = opts
        self._stop = False

    def stop(self): self._stop = True

    def run(self):
        base = dict(self.opts)
        for i, row in enumerate(self.rows):
            if self._stop: break
            url = row["url"]
            self.sig_update.emit(i, {"status":"Starting","progress":0})

            def hook(d):
                st = d.get("status")
                if st == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    got = d.get("downloaded_bytes") or 0
                    pct = int(got*100/total) if total else 0
                    self.sig_update.emit(i, {
                        "status":"Downloading",
                        "progress":pct,
                        "speed": f"{human_bytes(d.get('speed'))}/s" if d.get("speed") else "",
                    })
                elif st == "finished":
                    self.sig_update.emit(i, {"status":"Merging","progress":100})

            opts = dict(base); opts["progress_hooks"] = [hook]
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    try:
                        info = ydl.extract_info(url, download=False, process=False)
                        if info and info.get("title"):
                            self.sig_update.emit(i, {"title": info["title"]})
                    except Exception:
                        pass
                    
                    ydl.download([url])
                    self.sig_update.emit(i, {"status":"Done","progress":100})
            except yt_dlp.utils.DownloadError as e:
                self.sig_update.emit(i, {"status":"Error", "error": f"Download failed: {str(e)}"})
            except Exception as e:
                self.sig_update.emit(i, {"status":"Error", "error": f"An unexpected error occurred: {str(e)}"})
        self.sig_done.emit()

class Main(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setFixedSize(850, 650)
        self.settings = QtCore.QSettings(ORG_NAME, APP_NAME)
        self.worker: Optional[DLWorker] = None
        self._build_ui()
        self._restore()

    def _build_ui(self):
        cw = QtWidgets.QWidget(); self.setCentralWidget(cw)
        root = QtWidgets.QVBoxLayout(cw)

        row = QtWidgets.QHBoxLayout()
        self.url_input = QtWidgets.QLineEdit()
        self.url_input.setPlaceholderText("Paste a YouTube/Shorts/Playlist URL")
        self.url_input.setObjectName("url_input")
        btn_add = QtWidgets.QPushButton("Add")
        btn_add.clicked.connect(lambda: self._add_url(self.url_input.text().strip()))
        row.addWidget(self.url_input, 1); row.addWidget(btn_add)
        root.addLayout(row)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["URL","Title","Date Added","Progress","Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        group = QtWidgets.QGroupBox("Download Options")
        form = QtWidgets.QFormLayout()
        self.out_dir = QtWidgets.QLineEdit(str(Path.cwd() / "downloads"))
        self.out_dir.setObjectName("out_dir")
        btn_out = QtWidgets.QPushButton("Browse"); btn_out.clicked.connect(self._choose_outdir)
        out_row = QtWidgets.QHBoxLayout(); out_row.addWidget(self.out_dir,1); out_row.addWidget(btn_out)
        self.max_res = QtWidgets.QComboBox(); self.max_res.addItems(["No cap","2160","1440","1080","720"])
        self.format_combo = QtWidgets.QComboBox(); self.format_combo.addItems(["MKV (safe)","MP4"])
        form.addRow("Output folder", out_row)
        form.addRow("Max resolution", self.max_res)
        form.addRow("Format", self.format_combo)
        group.setLayout(form)
        root.addWidget(group)

        btns = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("Start"); self.btn_start.setObjectName("start_btn"); self.btn_start.clicked.connect(self._start)
        self.btn_stop = QtWidgets.QPushButton("Stop"); self.btn_stop.setObjectName("stop_btn"); self.btn_stop.setEnabled(False); self.btn_stop.clicked.connect(self._stop)
        btns.addWidget(self.btn_start); btns.addWidget(self.btn_stop); btns.addStretch(1)
        root.addLayout(btns)

    def _add_url(self, url: str):
        if not url: return
        r = self.table.rowCount(); self.table.insertRow(r)
        
        self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(url))
        self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(""))
        
        self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(datetime.now().strftime("%m/%d/%Y %I:%M:%S %p")))

        progress_bar = QtWidgets.QProgressBar()
        progress_bar.setValue(0)
        progress_bar.setTextVisible(True)
        self.table.setCellWidget(r, 3, progress_bar)
        
        self.table.setItem(r, 4, QtWidgets.QTableWidgetItem("Queued"))

        self.url_input.clear()
        
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeToContents)

    def _choose_outdir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self,"Select Output",self.out_dir.text())
        if d: self.out_dir.setText(d)

    def _start(self):
        if self.table.rowCount()==0: return
        if self.worker and self.worker.isRunning(): return

        outdir = Path(self.out_dir.text()); outdir.mkdir(parents=True, exist_ok=True)
        max_res_text = self.max_res.currentText()
        max_res_val = None if max_res_text=="No cap" else int(max_res_text)
        merge_fmt = "mkv" if self.format_combo.currentIndex()==0 else "mp4"

        ydl_opts = {
            "format": build_format(max_res_val),
            "merge_output_format": merge_fmt,
            "outtmpl": {"default": str(outdir/"%(title)s [%(id)s].%(ext)s")},
            "quiet": True,
            "geo_bypass": True,
            "extractor_args": {"youtube": {"player_client": ["android"]}},
            "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"},
            "http_chunk_size": 10 * 1024 * 1024,  
            "retries": 10,
            "fragment_retries": 10,
            "continuedl": True,
            "ignoreerrors": "only_download",
        }

        rows = [{"url":self.table.item(r,0).text()} for r in range(self.table.rowCount())]
        self.worker = DLWorker(rows, ydl_opts)
        self.worker.sig_update.connect(self._on_update)
        self.worker.sig_done.connect(self._on_done)
        self.btn_start.setEnabled(False); self.btn_stop.setEnabled(True)
        if not has_ffmpeg():
            QtWidgets.QMessageBox.warning(self, "FFmpeg", "FFmpeg not found on PATH. Install it or merges may fail.")
        self.worker.start()

    def _stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()

    @QtCore.Slot(int, dict)
    def _on_update(self, row: int, payload: Dict[str,Any]):
        if row>=self.table.rowCount(): return
        if "title" in payload: self.table.item(row,1).setText(payload["title"])
        if "progress" in payload: 
            progress_bar = self.table.cellWidget(row, 3)
            if progress_bar:
                progress_bar.setValue(payload['progress'])
        if "status" in payload: self.table.item(row,4).setText(payload["status"])
        if payload.get("error"): self.table.item(row,4).setText(payload["error"])

    @QtCore.Slot()
    def _on_done(self):
        self.btn_start.setEnabled(True); self.btn_stop.setEnabled(False)

    def _restore(self):
        self.out_dir.setText(self.settings.value("out_dir", self.out_dir.text()))
        self.max_res.setCurrentIndex(int(self.settings.value("max_res",0)))
        self.format_combo.setCurrentIndex(int(self.settings.value("fmt",0)))

    def closeEvent(self,e:QtGui.QCloseEvent):
        self.settings.setValue("out_dir", self.out_dir.text())
        self.settings.setValue("max_res", self.max_res.currentIndex())
        self.settings.setValue("fmt", self.format_combo.currentIndex())
        super().closeEvent(e)

def main():
    app = QtWidgets.QApplication(sys.argv)

    style_path = get_resource_path("style.qss")
    if os.path.exists(style_path):
        try:
            with open(style_path, "r") as f:
                style_sheet = f.read()
                app.setStyleSheet(style_sheet)
        except Exception as e:
            print(f"Error loading stylesheet: {e}")

    w = Main(); w.show()
    sys.exit(app.exec())

if __name__=="__main__":
    main()
