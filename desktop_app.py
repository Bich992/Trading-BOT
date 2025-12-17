import sys
import datetime as dt
import random
import time

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QComboBox, QPushButton,
    QTextEdit, QSplitter, QCheckBox, QGroupBox, QDockWidget,
    QFormLayout, QLineEdit, QMessageBox, QSpinBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QObject, QSettings
from PySide6.QtGui import QColor, QPalette

import pandas as pd

from charts.chart_widget import ChartWidget
from charts.performance_widget import PerformanceWidget
from charts.recap_widget import RecapWidget
from charts.live_state import LiveStateBuffer, TradeRender
from providers.binance_provider import BinanceProvider

from core.decision_engine import DecisionEngine
from core.paper_engine import PaperPortfolio
from core.auto_manager import AutoManager, AutoConfig
from core.timeframe_selector import choose_best_timeframe


TIMEFRAMES = ["1s", "5s", "10s", "30s", "1m", "3m", "5m", "15m", "30m", "1h"]


class MarketsWorker(QObject):
    done = Signal(list)
    fail = Signal(str)

    def __init__(self, provider: BinanceProvider):
        super().__init__()
        self.provider = provider

    def run(self):
        try:
            syms = self.provider.load_symbols()
            self.done.emit(syms)
        except Exception as e:
            self.fail.emit(str(e))


class SimulationFeed(QThread):
    """Fast fake feed for UI testing (10–50 updates/sec)."""

    def __init__(self, buffer: LiveStateBuffer, symbol: str, timeframe: str = "1s", freq: int = 20):
        super().__init__()
        self.buffer = buffer
        self.symbol = symbol
        self.freq = max(1, min(freq, 60))
        self.timeframe = timeframe
        self._running = True
        self._df = pd.DataFrame(columns=["Timestamp", "Open", "High", "Low", "Close", "Volume"])
        self._df.set_index("Timestamp", inplace=True)
        self._last_price = 20_000.0

    def stop(self):
        self._running = False

    def run(self):
        frame_seconds = self._tf_seconds(self.timeframe)
        while self._running:
            now = pd.Timestamp.utcnow().floor(f"{frame_seconds}s")
            drift = random.uniform(-5, 5)
            new_price = max(100.0, self._last_price + drift)
            if not self._df.empty and now == self._df.index[-1]:
                row = self._df.iloc[-1]
                row["High"] = max(row["High"], new_price)
                row["Low"] = min(row["Low"], new_price)
                row["Close"] = new_price
                self._df.iloc[-1] = row
            else:
                self._df.loc[now] = [self._last_price, new_price, new_price, new_price, random.uniform(1, 5)]
            self._last_price = new_price
            self.buffer.push_frame(self._df.tail(400))
            if random.random() < 0.05:
                marker = {
                    "ts": now,
                    "price": new_price,
                    "symbol": self.symbol,
                    "side": "buy" if random.random() > 0.5 else "sell",
                    "qty": random.uniform(0.1, 1),
                    "entry": new_price,
                    "exit": None,
                    "fee": new_price * 0.0005,
                    "pnl": random.uniform(-5, 5),
                    "pnl_pct": random.uniform(-0.5, 0.5),
                    "status": "SIM",
                }
                self.buffer.push_marker(marker)
            time.sleep(1 / self.freq)

    def _tf_seconds(self, tf: str) -> int:
        mapping = {"1s": 1, "5s": 5, "10s": 10, "30s": 30, "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}
        return mapping.get(tf, 60)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Alpha Desk – Pro Trading Bot Dashboard (PAPER)")
        self.resize(1920, 1100)
        self._apply_dark_theme()

        self.provider = BinanceProvider()
        self.engine = DecisionEngine()
        self.portfolio = PaperPortfolio(cash=1000.0, fee_rate=0.001)
        self.auto = AutoManager(self.engine, self.portfolio)
        self.cfg = AutoConfig()
        self.initial_cash = self.portfolio.cash

        self.learning_mode = True
        self.tf_candidates = ["1m", "5m", "15m", "1h"]
        self.last_tf_scores = {}

        self.current_symbol = None
        self.current_tf = "5m"
        self.last_df = None
        self.markers_by_symbol = {}
        self.bot_state = "LEARNING"
        self.peak_equity = self.initial_cash
        self.state_buffer = LiveStateBuffer()
        self.live_trades: list[TradeRender] = []
        self.render_timer = QTimer(self)
        self.render_timer.setInterval(150)
        self.render_timer.timeout.connect(self._render_live_snapshot)
        self.render_timer.start()
        self.sim_feed: SimulationFeed | None = None

        # Watchlist
        self.watchlist = [
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
            "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "MATIC/USDT", "DOT/USDT"
        ]

        # Indicators
        self.ema_1, self.ema_2, self.ema_3 = 20, 50, 200
        self.rsi_period = 14
        self.macd_fast, self.macd_slow, self.macd_sig = 12, 26, 9

        # AUTO loop
        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self._auto_multi_tick)

        self.settings = QSettings("AlphaDesk", "ProDashboard")

        main_root = QWidget()
        main_layout = QVBoxLayout(main_root)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        self.top_bar = self._build_top_bar()
        main_layout.addWidget(self.top_bar)

        self.shell_splitter = QSplitter(Qt.Vertical)
        self.shell_splitter.setChildrenCollapsible(False)

        self.body_splitter = QSplitter(Qt.Horizontal)
        self.body_splitter.setChildrenCollapsible(False)
        self.body_splitter.addWidget(self._build_left_panel())

        self.content_splitter = QSplitter(Qt.Horizontal)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.addWidget(self._build_center_panel())
        self.content_splitter.addWidget(self._build_right_panel())
        self.content_splitter.setSizes([1200, 520])

        self.body_splitter.addWidget(self.content_splitter)
        self.body_splitter.setSizes([220, 1500])

        self.shell_splitter.addWidget(self.body_splitter)
        self.shell_splitter.addWidget(self._build_bottom_panel())
        self.shell_splitter.setSizes([840, 220])

        main_layout.addWidget(self.shell_splitter)
        self.setCentralWidget(main_root)

        self.auto_dock = self._build_auto_dock()
        self.addDockWidget(Qt.RightDockWidgetArea, self.auto_dock)
        self._restore_ui_state()

        self._refresh_portfolio_view()
        self._refresh_trade_history()
        self._refresh_positions_list()
        self._refresh_watchlist()
        self._refresh_recap()
        self._update_top_bar()
        self._update_performance_panel()

    # ---------------- LEFT ----------------
    def _build_sidebar(self):
        sidebar = QWidget()
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        title = QLabel("Workspace")
        title.setStyleSheet("font-size:15px;font-weight:700;color:#e9ecef;")
        layout.addWidget(title)

        self.nav_list = QListWidget()
        self.nav_list.addItems([
            "Dashboard",
            "Markets",
            "Strategies",
            "Risk Control",
            "Trades",
            "Analytics",
            "Recap & Reports",
            "Settings",
        ])
        self.nav_list.setCurrentRow(0)
        self.nav_list.setStyleSheet(
            "QListWidget{background:#0f1116;color:#cfd8dc;border:1px solid #1f2933;}"
            "QListWidget::item:selected{background:#1c7ed6;}"
        )
        layout.addWidget(self.nav_list)

        return sidebar

    def _build_left_panel(self):
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        # -- Market browser section --
        market_box = QWidget()
        m_layout = QVBoxLayout(market_box)
        m_layout.addWidget(QLabel("Modalità: Apprendimento Virtuale (PAPER)"))

        row = QHBoxLayout()
        self.btn_load = QPushButton("Load ALL Binance Symbols")
        self.btn_load.clicked.connect(self._load_all_markets_async)
        row.addWidget(self.btn_load)
        m_layout.addLayout(row)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Search symbol… e.g. BTC/USDT")
        self.txt_search.textChanged.connect(self._apply_market_filter)
        m_layout.addWidget(self.txt_search)

        m_layout.addWidget(QLabel("Market Browser"))
        self.list_markets = QListWidget()
        self.list_markets.setAlternatingRowColors(True)
        m_layout.addWidget(self.list_markets, 2)

        btn_row = QHBoxLayout()
        self.btn_add_watch = QPushButton("Add → Watchlist")
        self.btn_add_watch.clicked.connect(self._add_selected_to_watchlist)
        self.btn_remove_watch = QPushButton("Remove from Watchlist")
        self.btn_remove_watch.clicked.connect(self._remove_selected_from_watchlist)
        btn_row.addWidget(self.btn_add_watch)
        btn_row.addWidget(self.btn_remove_watch)
        m_layout.addLayout(btn_row)

        # -- Watchlist section --
        watch_box = QWidget()
        w_layout = QVBoxLayout(watch_box)
        w_layout.addWidget(QLabel("Watchlist (AUTO works here)"))
        self.list_watch = QListWidget()
        self.list_watch.itemClicked.connect(self._select_asset_from_watchlist)
        self.list_watch.setAlternatingRowColors(True)
        w_layout.addWidget(self.list_watch, 2)

        # -- Portfolio section --
        portfolio_box = QWidget()
        p_layout = QVBoxLayout(portfolio_box)
        p_layout.addWidget(QLabel("Portfolio (PAPER)"))
        self.txt_portfolio = QTextEdit()
        self.txt_portfolio.setReadOnly(True)
        p_layout.addWidget(self.txt_portfolio, 2)

        p_layout.addWidget(QLabel("Open Positions (green=profit, red=loss)"))
        self.list_positions = QListWidget()
        p_layout.addWidget(self.list_positions, 2)

        splitter.addWidget(market_box)
        splitter.addWidget(watch_box)
        splitter.addWidget(portfolio_box)
        splitter.setSizes([400, 260, 260])
        return splitter

    # ---------------- CENTER ----------------
    def _build_center_panel(self):
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self.lbl_asset = QLabel("Selected asset: —")
        self.lbl_asset.setStyleSheet("font-size:18px;font-weight:700;")
        header.addWidget(self.lbl_asset)

        self.lbl_tf_auto = QLabel("TF auto: —")
        self.lbl_tf_auto.setStyleSheet("color:#0b7285;font-weight:600;")
        header.addWidget(self.lbl_tf_auto)

        header.addStretch()

        self.chk_show_ema = QCheckBox("EMA")
        self.chk_show_ema.setChecked(False)
        self.chk_show_rsi = QCheckBox("RSI")
        self.chk_show_macd = QCheckBox("MACD")
        ind_hint = QLabel("Indicators (optional)")
        ind_hint.setStyleSheet("color:#666;font-size:12px;")
        for w in (self.chk_show_ema, self.chk_show_rsi, self.chk_show_macd):
            w.stateChanged.connect(lambda _: self._refresh_chart(force=True))
        header.addWidget(ind_hint)
        header.addWidget(self.chk_show_ema)
        header.addWidget(self.chk_show_rsi)
        header.addWidget(self.chk_show_macd)

        self.cmb_tf = QComboBox()
        self.cmb_tf.addItems(TIMEFRAMES)
        self.cmb_tf.setCurrentText(self.current_tf)
        self.cmb_tf.currentTextChanged.connect(self._change_tf)
        header.addWidget(QLabel("Chart TF"))
        header.addWidget(self.cmb_tf)

        self.btn_refresh = QPushButton("Refresh Chart")
        self.btn_refresh.clicked.connect(self._refresh_chart)
        header.addWidget(self.btn_refresh)

        layout.addLayout(header)

        self.chart_perf_splitter = QSplitter(Qt.Vertical)
        self.chart_perf_splitter.setChildrenCollapsible(False)

        self.chart = ChartWidget()
        self.performance = PerformanceWidget()
        self.performance.setMinimumHeight(180)
        self.chart_perf_splitter.addWidget(self.chart)
        self.chart_perf_splitter.addWidget(self.performance)
        self.chart_perf_splitter.setSizes([900, 300])

        layout.addWidget(self.chart_perf_splitter)
        return wrapper

    def _add_form_field(self, form: QFormLayout, label: str, widget: QWidget, helper: str, warn: bool = False):
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(widget)
        helper_lbl = QLabel(helper)
        helper_lbl.setStyleSheet(
            "color:#868e96;font-size:11px;" + ("font-weight:700;color:#f08c00;" if warn else "")
        )
        layout.addWidget(helper_lbl)
        form.addRow(label, wrapper)

    def _build_auto_dock(self) -> QDockWidget:
        dock = QDockWidget("Auto Multi-Asset + Short", self)
        dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable)
        dock.setMinimumWidth(340)
        dock.setMaximumWidth(560)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        auto_box = QGroupBox("AUTO Multi-Asset (PAPER) – Risk-Reduced")
        f = QFormLayout(auto_box)

        self.chk_auto = QCheckBox("Enable AUTO Multi-Asset")
        self.chk_auto.stateChanged.connect(self._toggle_auto)

        self.sp_interval = QSpinBox(); self.sp_interval.setRange(1, 3600); self.sp_interval.setValue(self.cfg.interval_sec)
        self.sp_conf_entry = QDoubleSpinBox(); self.sp_conf_entry.setRange(0, 1); self.sp_conf_entry.setDecimals(2); self.sp_conf_entry.setValue(self.cfg.conf_entry)
        self.sp_conf_add = QDoubleSpinBox(); self.sp_conf_add.setRange(0, 1); self.sp_conf_add.setDecimals(2); self.sp_conf_add.setValue(self.cfg.conf_add)

        self.sp_max_assets = QSpinBox(); self.sp_max_assets.setRange(1, 50); self.sp_max_assets.setValue(self.cfg.max_open_assets)
        self.sp_cooldown = QSpinBox(); self.sp_cooldown.setRange(0, 3600); self.sp_cooldown.setValue(self.cfg.cooldown_sec)

        self.cmb_add_mode = QComboBox()
        self.cmb_add_mode.addItems(["OFF", "PYRAMID", "MEANREV"])
        self.cmb_add_mode.setCurrentText(self.cfg.add_mode)

        self.sp_max_legs = QSpinBox(); self.sp_max_legs.setRange(1, 10); self.sp_max_legs.setValue(self.cfg.max_legs_per_asset)

        self.chk_short = QCheckBox("Allow SHORT")
        self.chk_short.setChecked(self.cfg.allow_short)

        self.cmb_size_mode = QComboBox()
        self.cmb_size_mode.addItems(["FIXED", "AUTO_RISK"])
        self.cmb_size_mode.setCurrentText(self.cfg.size_mode)

        self.sp_fixed = QDoubleSpinBox(); self.sp_fixed.setRange(1, 1_000_000); self.sp_fixed.setDecimals(2); self.sp_fixed.setValue(self.cfg.fixed_notional)
        self.sp_riskpct = QDoubleSpinBox(); self.sp_riskpct.setRange(0, 0.10); self.sp_riskpct.setDecimals(3); self.sp_riskpct.setValue(self.cfg.risk_per_trade_pct)

        self.sp_fee = QDoubleSpinBox(); self.sp_fee.setRange(0, 0.01); self.sp_fee.setDecimals(4); self.sp_fee.setValue(self.portfolio.fee_rate)
        self.sp_cash = QDoubleSpinBox(); self.sp_cash.setRange(10, 1_000_000); self.sp_cash.setDecimals(2); self.sp_cash.setValue(self.portfolio.cash)

        btn_apply = QPushButton("Apply AUTO Settings")
        btn_apply.clicked.connect(self._apply_auto_settings)

        btn_reset = QPushButton("Reset PAPER Portfolio (cash/fee)")
        btn_reset.clicked.connect(self._reset_portfolio)

        f.addRow(self.chk_auto)
        self._add_form_field(f, "Interval (sec)", self.sp_interval, "Timer UI/auto loop. 1–3600 sec; shorter = faster reaction")
        self._add_form_field(f, "Conf entry", self.sp_conf_entry, "Confidence threshold to open a trade [0-1]")
        self._add_form_field(f, "Conf add", self.sp_conf_add, "Confidence needed to add to a position [0-1]")
        self._add_form_field(f, "Max open assets", self.sp_max_assets, "Cap simultaneous assets to reduce overload")
        self._add_form_field(f, "Cooldown (sec)", self.sp_cooldown, "Pause after a trade to avoid overtrading")
        self._add_form_field(f, "Add mode", self.cmb_add_mode, "PYRAMID averages up, MEANREV buys dips")
        self._add_form_field(f, "Max legs/asset", self.sp_max_legs, "Number of scaling legs per symbol")
        f.addRow(self.chk_short)
        self._add_form_field(f, "Size mode", self.cmb_size_mode, "FIXED uses notional; AUTO_RISK sizes by risk %")
        self._add_form_field(f, "Fixed notional", self.sp_fixed, "USDT notional per entry when size=FIXED")
        self._add_form_field(f, "Risk per trade (AUTO_RISK)", self.sp_riskpct, "Max % equity at risk per trade", warn=True)
        self._add_form_field(f, "Fee rate", self.sp_fee, "Exchange taker fee assumption", warn=True)
        self._add_form_field(f, "Initial cash", self.sp_cash, "Reset PAPER equity; use caution in live")
        f.addRow(btn_apply)
        f.addRow(btn_reset)

        layout.addWidget(auto_box)

        stories_box = QGroupBox("Stories / Decision log")
        s_layout = QVBoxLayout(stories_box)
        self.txt_stories = QTextEdit()
        self.txt_stories.setReadOnly(True)
        s_layout.addWidget(self.txt_stories)
        layout.addWidget(stories_box, 1)

        dock.setWidget(container)
        return dock

    # ---------------- RIGHT ----------------
    def _build_right_panel(self):
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        thoughts_box = QWidget()
        t_layout = QVBoxLayout(thoughts_box)
        t_layout.addWidget(QLabel("Bot Thoughts"))
        self.txt_thoughts = QTextEdit()
        self.txt_thoughts.setReadOnly(True)
        t_layout.addWidget(self.txt_thoughts, 4)

        live_box = QWidget()
        lv_layout = QVBoxLayout(live_box)
        lv_layout.addWidget(QLabel("Trades Live"))
        self.tbl_trades_live = QTableWidget(0, 9)
        self.tbl_trades_live.setHorizontalHeaderLabels([
            "Asset", "Side", "Qty", "Entry", "Last", "Notional", "Fee", "PnL", "Status"
        ])
        self.tbl_trades_live.horizontalHeader().setStretchLastSection(True)
        lv_layout.addWidget(self.tbl_trades_live, 5)

        trades_box = QWidget()
        tr_layout = QVBoxLayout(trades_box)
        tr_layout.addWidget(QLabel("Trade History (PAPER)"))
        self.txt_trades = QTextEdit()
        self.txt_trades.setReadOnly(True)
        tr_layout.addWidget(self.txt_trades, 4)

        recap_box = QWidget()
        r_layout = QVBoxLayout(recap_box)
        header = QHBoxLayout()
        header.addWidget(QLabel("Recap Apprendimento Virtuale"))
        self.btn_recap = QPushButton("Aggiorna recap")
        self.btn_recap.clicked.connect(self._refresh_recap)
        header.addWidget(self.btn_recap)
        header.addStretch()
        r_layout.addLayout(header)

        self.recap_chart = RecapWidget()
        r_layout.addWidget(self.recap_chart, 5)

        self.txt_recap = QTextEdit()
        self.txt_recap.setReadOnly(True)
        r_layout.addWidget(self.txt_recap, 3)

        splitter.addWidget(thoughts_box)
        splitter.addWidget(live_box)
        splitter.addWidget(trades_box)
        splitter.addWidget(recap_box)
        splitter.setSizes([220, 260, 240, 380])

        return splitter

    def _build_bottom_panel(self):
        panel = QWidget()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        log_box = QGroupBox("Live Log")
        l_layout = QVBoxLayout(log_box)
        self.txt_stories_bottom = QTextEdit()
        self.txt_stories_bottom.setReadOnly(True)
        self.txt_stories_bottom.setStyleSheet("background:#0f1116;color:#e9ecef;")
        l_layout.addWidget(self.txt_stories_bottom)

        trades_box = QGroupBox("Trade Tape")
        t_layout = QVBoxLayout(trades_box)
        self.txt_trades_bottom = QTextEdit()
        self.txt_trades_bottom.setReadOnly(True)
        self.txt_trades_bottom.setStyleSheet("background:#0f1116;color:#e9ecef;")
        t_layout.addWidget(self.txt_trades_bottom)

        layout.addWidget(log_box, 3)
        layout.addWidget(trades_box, 2)
        return panel

    def _build_top_bar(self):
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(16)

        def badge(text: str, color: str):
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"padding:6px 10px;border-radius:6px;background:{color};color:white;font-weight:600;"
            )
            return lbl

        self.lbl_mode = badge("PAPER", "#364fc7")
        self.lbl_state = badge("LEARNING", "#e67700")
        layout.addWidget(self.lbl_mode)
        layout.addWidget(self.lbl_state)

        self.lbl_tf_active = QLabel("Timeframes: –")
        self.lbl_tf_active.setStyleSheet("color:#e9ecef;font-weight:600;")
        layout.addWidget(self.lbl_tf_active)

        self.lbl_equity = QLabel("Equity: —")
        self.lbl_equity.setStyleSheet("color:#e9ecef;font-weight:700;font-size:15px;")
        layout.addWidget(self.lbl_equity)

        self.lbl_dd = QLabel("Drawdown: —")
        self.lbl_dd.setStyleSheet("color:#faa307;font-weight:600;")
        layout.addWidget(self.lbl_dd)

        self.lbl_alert = badge("Alert: None", "#2b8a3e")
        layout.addWidget(self.lbl_alert)

        layout.addStretch()

        return wrapper

    # ---------------- Markets load/search ----------------
    def _load_all_markets_async(self):
        self.btn_load.setEnabled(False)
        self._append_story("Loading Binance symbols…")

        self.worker_thread = QThread()
        self.worker = MarketsWorker(self.provider)
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.done.connect(self._on_markets_loaded)
        self.worker.fail.connect(self._on_markets_failed)
        self.worker.done.connect(lambda _: self.worker_thread.quit())
        self.worker.fail.connect(lambda _: self.worker_thread.quit())
        self.worker_thread.finished.connect(lambda: self.btn_load.setEnabled(True))

        self.worker_thread.start()

    def _on_markets_loaded(self, symbols):
        self.all_symbols = symbols
        self._append_story(f"Loaded {len(symbols)} symbols.")
        self._apply_market_filter()

    def _on_markets_failed(self, msg):
        self._append_story(f"Load symbols failed: {msg}")

    def _apply_market_filter(self):
        self.list_markets.clear()
        if not hasattr(self, "all_symbols"):
            return
        q = self.txt_search.text().strip().upper()
        matches = [s for s in self.all_symbols if q in s.upper()] if q else self.all_symbols
        for s in matches[:5000]:
            self.list_markets.addItem(QListWidgetItem(s))

    # ---------------- Watchlist ----------------
    def _refresh_watchlist(self):
        self.list_watch.clear()
        for s in self.watchlist:
            self.list_watch.addItem(QListWidgetItem(s))

        if self.watchlist and (self.current_symbol is None or self.current_symbol not in self.watchlist):
            self.list_watch.setCurrentRow(0)
            self._select_asset_from_watchlist(self.list_watch.item(0))

    def _add_selected_to_watchlist(self):
        item = self.list_markets.currentItem()
        if not item:
            return
        sym = item.text()
        if sym not in self.watchlist:
            self.watchlist.append(sym)
            self._append_story(f"Watchlist + {sym}")
            self._refresh_watchlist()

    def _remove_selected_from_watchlist(self):
        item = self.list_watch.currentItem()
        if not item:
            return
        sym = item.text()
        self.watchlist = [s for s in self.watchlist if s != sym]
        self._append_story(f"Watchlist - {sym}")
        self._refresh_watchlist()

    def _select_asset_from_watchlist(self, item):
        self.current_symbol = item.text()
        self.lbl_asset.setText(f"Selected asset: {self.current_symbol}")
        self._start_simulation_feed()
        self._refresh_chart()
        self._refresh_positions_list()

    # ---------------- Chart ----------------
    def _change_tf(self, tf):
        self.current_tf = tf
        self._start_simulation_feed()
        self._refresh_chart(force=True)

    def _start_simulation_feed(self):
        if self.sim_feed:
            self.sim_feed.stop()
            self.sim_feed.wait(200)
        symbol = self.current_symbol or "SIM/USDT"
        self.sim_feed = SimulationFeed(self.state_buffer, symbol=symbol, timeframe=self.current_tf, freq=25)
        self.sim_feed.start()

    def _refresh_chart(self, force: bool = False):
        if not self.current_symbol:
            return
        try:
            self.last_df = self.provider.fetch_ohlc(self.current_symbol, self.current_tf, limit=400)
            self.state_buffer.push_frame(self.last_df)
            markers = self._markers_for_symbol(self.current_symbol)
            self.state_buffer.clear_markers()
            self.state_buffer.extend_markers(markers)
            tf_info = self.last_tf_scores.get(self.current_symbol)
            if tf_info:
                self.lbl_tf_auto.setText(f"TF auto: {tf_info.timeframe} ({tf_info.regime})")
                chart_title = f"{self.current_symbol} @ {self.current_tf} | best {tf_info.timeframe} ({tf_info.regime})"
            else:
                self.lbl_tf_auto.setText("TF auto: —")
                chart_title = f"{self.current_symbol} @ {self.current_tf}"
            self.chart.set_indicators(
                ema_periods=(self.ema_1, self.ema_2, self.ema_3),
                rsi_period=self.rsi_period,
                macd_params=(self.macd_fast, self.macd_slow, self.macd_sig),
                show_ema=self.chk_show_ema.isChecked(),
                show_rsi=self.chk_show_rsi.isChecked(),
                show_macd=self.chk_show_macd.isChecked(),
            )
            if force:
                self.chart.update_snapshot(self.last_df, markers=markers, title=chart_title)
        except Exception as e:
            self._append_story(f"Chart load error: {e}")

    # ---------------- AUTO config ----------------
    def _apply_auto_settings(self):
        self.cfg.interval_sec = int(self.sp_interval.value())
        self.cfg.conf_entry = float(self.sp_conf_entry.value())
        self.cfg.conf_add = float(self.sp_conf_add.value())
        self.cfg.max_open_assets = int(self.sp_max_assets.value())
        self.cfg.cooldown_sec = int(self.sp_cooldown.value())
        self.cfg.add_mode = self.cmb_add_mode.currentText()
        self.cfg.max_legs_per_asset = int(self.sp_max_legs.value())
        self.cfg.allow_short = self.chk_short.isChecked()
        self.cfg.size_mode = self.cmb_size_mode.currentText()
        self.cfg.fixed_notional = float(self.sp_fixed.value())
        self.cfg.risk_per_trade_pct = float(self.sp_riskpct.value())

        self.portfolio.fee_rate = float(self.sp_fee.value())

        self._append_story("AUTO settings applied.")

        if self.chk_auto.isChecked():
            self.auto_timer.start(self.cfg.interval_sec * 1000)
        self._update_top_bar()

    def _reset_portfolio(self):
        cash = float(self.sp_cash.value())
        fee = float(self.sp_fee.value())
        self.portfolio = PaperPortfolio(cash=cash, fee_rate=fee)
        self.auto = AutoManager(self.engine, self.portfolio)
        self.initial_cash = cash
        self.last_tf_scores = {}
        self._append_story(f"PAPER reset: cash={cash:.2f}, fee={fee:.4f}")
        self._refresh_portfolio_view()
        self._refresh_trade_history()
        self._refresh_positions_list()
        self._refresh_recap()
        self._update_performance_panel()
        self._update_top_bar()

    def _toggle_auto(self, _):
        if self.chk_auto.isChecked():
            if not self.watchlist:
                QMessageBox.warning(self, "AUTO", "Watchlist is empty.")
                self.chk_auto.setChecked(False)
                return
            self.auto_timer.start(self.cfg.interval_sec * 1000)
            self._append_story(f"AUTO Multi-Asset enabled (interval={self.cfg.interval_sec}s)")
        else:
            self.auto_timer.stop()
            self._append_story("AUTO Multi-Asset disabled")

    # ---------------- AUTO multi tick ----------------
    def _auto_multi_tick(self):
        ohlc_by_symbol = {}
        tf_scores = {}
        now = dt.datetime.now()

        for s in self.watchlist:
            frames = {}
            for tf in self.tf_candidates:
                try:
                    frames[tf] = self.provider.fetch_ohlc(s, tf, limit=220)
                except Exception:
                    frames[tf] = None

            best = choose_best_timeframe(frames)
            tf_scores[s] = best
            ohlc_by_symbol[s] = frames.get(best.timeframe)

        self.last_tf_scores = tf_scores

        logs = self.auto.step(self.watchlist, ohlc_by_symbol, now, self.cfg, best_timeframes=tf_scores)
        for line in logs:
            self._append_story(line)

            # simple markers on selected chart if same symbol
            if self.current_symbol and line.startswith(self.current_symbol):
                # best-effort marker
                df = ohlc_by_symbol.get(self.current_symbol)
                if df is not None and not df.empty:
                    price = float(df["Close"].iloc[-1])
                    ts = df.index[-1].to_pydatetime()
                    if "ENTRY LONG" in line or "ADD LONG" in line:
                        self._add_marker(self.current_symbol, "buy", ts, price)
                    if "ENTRY SHORT" in line or "ADD SHORT" in line:
                        self._add_marker(self.current_symbol, "sell", ts, price)
                    if "SCALE-OUT" in line:
                        self._add_marker(self.current_symbol, "sell", ts, price)

        self._refresh_portfolio_view()
        self._refresh_trade_history()
        self._refresh_positions_list()
        self._refresh_recap()
        self._update_top_bar()
        self._update_performance_panel()

        # refresh chart only for selected symbol (avoid heavy UI)
        if self.current_symbol:
            self._refresh_chart()

    # ---------------- UI helpers ----------------
    def _add_marker(self, symbol: str, kind: str, ts: dt.datetime, price: float):
        self.markers_by_symbol.setdefault(symbol, []).append({
            "ts": pd.Timestamp(ts),
            "price": price,
            "kind": kind
        })
        if len(self.markers_by_symbol[symbol]) > 500:
            self.markers_by_symbol[symbol] = self.markers_by_symbol[symbol][-500:]

    def _markers_for_symbol(self, symbol: str):
        markers = []
        for t in self.portfolio.trades:
            if t.symbol != symbol:
                continue
            pnl_pct = 0
            notional = t.qty * t.price if t.qty else 0
            if notional:
                pnl_pct = (t.pnl_realized / notional) * 100
            markers.append(TradeRender(
                ts=pd.Timestamp(t.ts),
                symbol=t.symbol,
                side=t.side,
                qty=t.qty,
                price=t.price,
                entry=t.price,
                exit=None,
                fee=t.fee,
                pnl=t.pnl_realized,
                pnl_pct=pnl_pct,
                status="CLOSED" if "CLOSE" in t.note else "OPEN",
            ).to_marker())
        markers.extend(self.markers_by_symbol.get(symbol, []))
        return markers

    def _append_story(self, line: str):
        prev = self.txt_stories.toPlainText().strip()
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        new_line = f"[{stamp}] {line}"
        self.txt_stories.setText((prev + "\n" + new_line).strip() if prev else new_line)
        log_prev = self.txt_stories_bottom.toPlainText().strip()
        self.txt_stories_bottom.setText((log_prev + "\n" + new_line).strip() if log_prev else new_line)

    def _refresh_portfolio_view(self):
        prices = {}
        if self.current_symbol and self.last_df is not None and not self.last_df.empty:
            prices[self.current_symbol] = float(self.last_df["Close"].iloc[-1])
        eq = self.portfolio.equity(prices)

        lines = [
            f"Cash: {self.portfolio.cash:.2f}",
            f"Equity: {eq:.2f}",
            f"Fee rate: {self.portfolio.fee_rate:.4f}",
            f"Total fee pagate: {self.portfolio.total_fees():.4f}",
            f"PnL realizzato: {self.portfolio.realized_pnl():.4f}",
            "",
            "Positions (net):"
        ]
        for sym, book in self.portfolio.books.items():
            nq = book.net_qty()
            if abs(nq) > 0:
                lines.append(f"- {sym}: net_qty={nq:.6f} avg={book.avg_entry():.6f} legs={book.legs_count()}")
        self.txt_portfolio.setText("\n".join(lines))
        self._update_top_bar()

    def _refresh_positions_list(self):
        self.list_positions.clear()

        # Use selected symbol last price if available; otherwise we can’t compute precise per-symbol uPnL here
        if not self.current_symbol or self.last_df is None or self.last_df.empty:
            # still show net positions without coloring
            for sym, book in self.portfolio.books.items():
                nq = book.net_qty()
                if abs(nq) > 0:
                    self.list_positions.addItem(QListWidgetItem(f"{sym} net={nq:.6f} legs={book.legs_count()}"))
            return

        last_price = float(self.last_df["Close"].iloc[-1])

        for sym, book in self.portfolio.books.items():
            nq = book.net_qty()
            if abs(nq) <= 0:
                continue

            # color uPnL only for selected symbol price (fast). Others shown neutral.
            if sym == self.current_symbol:
                upnl = self.portfolio.unrealized_pnl(sym, last_price)
                txt = f"{sym} | net={nq:.6f} avg={book.avg_entry():.6f} legs={book.legs_count()} | uPnL={upnl:.4f}"
                item = QListWidgetItem(txt)
                item.setForeground(Qt.darkGreen if upnl >= 0 else Qt.red)
            else:
                item = QListWidgetItem(f"{sym} | net={nq:.6f} legs={book.legs_count()} (select to price uPnL)")
            self.list_positions.addItem(item)

    def _refresh_trade_history(self):
        lines = []
        for t in self.portfolio.trades[-180:]:
            lines.append(
                f"{t.ts.strftime('%Y-%m-%d %H:%M:%S')} | {t.order_type.upper()} | {t.side.upper()} {t.symbol} "
                f"| qty={t.qty:.6f} @ {t.price:.6f} | fee={t.fee:.4f} | pnlR={t.pnl_realized:.4f} | {t.note}"
            )
        self.txt_trades.setText("\n".join(lines) if lines else "No trades yet.")
        self.txt_trades_bottom.setText("\n".join(lines) if lines else "No trades yet.")
        if self.current_symbol:
            self.state_buffer.clear_markers()
            self.state_buffer.extend_markers(self._markers_for_symbol(self.current_symbol))
        self._refresh_trades_live()

    def _refresh_recap(self):
        trades = list(self.portfolio.trades)
        total_fees = self.portfolio.total_fees()
        realized = self.portfolio.realized_pnl()
        gross = realized + total_fees
        win_count = sum(1 for t in trades if t.pnl_realized > 0)
        loss_count = sum(1 for t in trades if t.pnl_realized < 0)
        tf_lines = []
        for sym, score in self.last_tf_scores.items():
            tf_lines.append(f"- {sym}: {score.timeframe} ({score.regime}) score={score.score:.2f}")

        strat_notes = [
            "Selezione timeframe automatica per minimizzare chop/rischio",
            "Gestione fee inclusa in ogni trade (pnl realizzato netto)",
            "Pyramid/mean-reversion controllate dal rischio ATR/RSI"
        ]

        lines = [
            "Recap simulazione (pronto per il live solo dopo revisione):",
            f"- Modalità virtuale attiva: {self.learning_mode}",
            f"- Operazioni simulate: {len(trades)} (win={win_count}, loss={loss_count})",
            f"- Risultato lordo: {gross:.4f}",
            f"- Fee e costi stimati: {total_fees:.4f}",
            f"- PnL netto (realizzato): {realized:.4f}",
            f"- Equity di partenza: {self.initial_cash:.2f}",
            "- Timeframe ottimali recenti:",
            *(tf_lines or ["  nessun dato ancora"]),
            "- Strategie migliorate:",
            *(f"  • {s}" for s in strat_notes)
        ]

        self.txt_recap.setText("\n".join(lines))
        self.recap_chart.plot(trades, self.initial_cash)
        self._update_top_bar()

    def _refresh_trades_live(self, last_price: float | None = None):
        rows = []
        price_hint = last_price
        if price_hint is None and self.last_df is not None and not self.last_df.empty:
            price_hint = float(self.last_df["Close"].iloc[-1])

        for sym, book in self.portfolio.books.items():
            nq = book.net_qty()
            if abs(nq) <= 0:
                continue
            entry = book.avg_entry()
            notional = abs(nq * entry)
            upnl = self.portfolio.unrealized_pnl(sym, price_hint) if price_hint else 0.0
            pnl_pct = (upnl / notional * 100) if notional else 0.0
            rows.append({
                "asset": sym,
                "side": "LONG" if nq > 0 else "SHORT",
                "qty": nq,
                "entry": entry,
                "last": price_hint or 0,
                "notional": notional,
                "fee": self.portfolio.fee_rate * notional,
                "pnl": upnl,
                "pnl_pct": pnl_pct,
                "status": "OPEN",
            })

        for t in reversed(self.portfolio.trades[-50:]):
            notional = abs(t.qty * t.price)
            pnl_pct = (t.pnl_realized / notional * 100) if notional else 0.0
            rows.append({
                "asset": t.symbol,
                "side": t.side.upper(),
                "qty": t.qty,
                "entry": t.price,
                "last": price_hint or t.price,
                "notional": notional,
                "fee": t.fee,
                "pnl": t.pnl_realized,
                "pnl_pct": pnl_pct,
                "status": "CLOSED" if "CLOSE" in t.note else t.note or "CLOSED",
            })

        self.tbl_trades_live.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = [
                row["asset"], row["side"], f"{row['qty']:.6f}", f"{row['entry']:.4f}",
                f"{row['last']:.4f}", f"{row['notional']:.2f}", f"{row['fee']:.4f}",
                f"{row['pnl']:.4f} ({row['pnl_pct']:.2f}%)", row["status"],
            ]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                if c == 7:  # pnl column
                    item.setForeground(Qt.darkGreen if row["pnl"] >= 0 else Qt.red)
                self.tbl_trades_live.setItem(r, c, item)

    def _update_top_bar(self):
        prices = {}
        if self.current_symbol and self.last_df is not None and not self.last_df.empty:
            prices[self.current_symbol] = float(self.last_df["Close"].iloc[-1])

        equity = self.portfolio.equity(prices)
        self.peak_equity = max(self.peak_equity, equity)
        dd = 0 if self.peak_equity == 0 else (equity - self.peak_equity) / self.peak_equity * 100
        self.lbl_equity.setText(f"Equity: {equity:.2f} USDT")
        self.lbl_dd.setText(f"Drawdown: {dd:.2f}%")
        self.lbl_dd.setStyleSheet(
            "color:#e03131;font-weight:700;" if dd < -2 else "color:#e9ecef;font-weight:700;"
        )

        tf_text = ", ".join(self.tf_candidates)
        self.lbl_tf_active.setText(f"Timeframes: {tf_text} | Chart: {self.current_tf}")

        if self.chk_auto.isChecked():
            self.lbl_state.setText("TRADING")
            self.lbl_state.setStyleSheet("padding:6px 10px;border-radius:6px;background:#2f9e44;color:white;font-weight:700;")
        else:
            self.lbl_state.setText(self.bot_state)
            self.lbl_state.setStyleSheet("padding:6px 10px;border-radius:6px;background:#e67700;color:white;font-weight:700;")

        alert_msg = "Stable"
        alert_color = "#2b8a3e"
        if dd < -5:
            alert_msg = "Drawdown risk"
            alert_color = "#e03131"
        elif not self.watchlist:
            alert_msg = "No assets selected"
            alert_color = "#f08c00"
        self.lbl_alert.setText(f"Alert: {alert_msg}")
        self.lbl_alert.setStyleSheet(
            f"padding:6px 10px;border-radius:6px;background:{alert_color};color:white;font-weight:700;"
        )

    def _render_live_snapshot(self):
        df, markers, last_price = self.state_buffer.snapshot()
        if df is not None and not df.empty:
            tf_info = self.last_tf_scores.get(self.current_symbol) if self.current_symbol else None
            if tf_info:
                chart_title = f"{self.current_symbol} @ {self.current_tf} | best {tf_info.timeframe} ({tf_info.regime})"
            else:
                chart_title = f"{self.current_symbol or 'SIM'} @ {self.current_tf}"
            self.chart.set_indicators(
                ema_periods=(self.ema_1, self.ema_2, self.ema_3),
                rsi_period=self.rsi_period,
                macd_params=(self.macd_fast, self.macd_slow, self.macd_sig),
                show_ema=self.chk_show_ema.isChecked(),
                show_rsi=self.chk_show_rsi.isChecked(),
                show_macd=self.chk_show_macd.isChecked(),
            )
            self.chart.update_snapshot(df, markers=markers, title=chart_title)
            self.last_df = df
            self._update_top_bar()
            self._update_performance_panel()
        self._refresh_trades_live(last_price)

    def _update_performance_panel(self):
        if not hasattr(self, "performance"):
            return
        prices = {}
        if self.current_symbol and self.last_df is not None and not self.last_df.empty:
            prices[self.current_symbol] = float(self.last_df["Close"].iloc[-1])
        now_equity = self.portfolio.equity(prices)
        self.performance.update_performance(self.portfolio.trades, self.initial_cash, now_equity)

    def closeEvent(self, event):
        self._save_ui_state()
        super().closeEvent(event)

    def _restore_ui_state(self):
        geom = self.settings.value("geometry")
        if geom:
            self.restoreGeometry(geom)
        state = self.settings.value("windowState")
        if state:
            self.restoreState(state)
        self._restore_splitter_sizes(self.shell_splitter, "shell_splitter")
        self._restore_splitter_sizes(self.body_splitter, "body_splitter")
        self._restore_splitter_sizes(self.content_splitter, "content_splitter")
        self._restore_splitter_sizes(self.chart_perf_splitter, "chart_perf_splitter", default=[900, 260])

        dock_area = self.settings.value("autoDockArea")
        if dock_area is not None:
            self.addDockWidget(Qt.DockWidgetArea(int(dock_area)), self.auto_dock)
        floating = self.settings.value("autoDockFloating")
        if floating is not None:
            self.auto_dock.setFloating(floating in [True, "true", "1"])

    def _save_ui_state(self):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        self._save_splitter_sizes(self.shell_splitter, "shell_splitter")
        self._save_splitter_sizes(self.body_splitter, "body_splitter")
        self._save_splitter_sizes(self.content_splitter, "content_splitter")
        self._save_splitter_sizes(self.chart_perf_splitter, "chart_perf_splitter")
        self.settings.setValue("autoDockArea", int(self.dockWidgetArea(self.auto_dock)))
        self.settings.setValue("autoDockFloating", self.auto_dock.isFloating())

    def _restore_splitter_sizes(self, splitter: QSplitter, key: str, default: list[int] | None = None):
        sizes = self.settings.value(key)
        if sizes:
            splitter.setSizes([int(s) for s in sizes])
        elif default:
            splitter.setSizes(default)

    def _save_splitter_sizes(self, splitter: QSplitter, key: str):
        self.settings.setValue(key, splitter.sizes())

    def _apply_dark_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(10, 12, 16))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(15, 17, 22))
        palette.setColor(QPalette.AlternateBase, QColor(23, 26, 32))
        palette.setColor(QPalette.Text, QColor(235, 240, 243))
        palette.setColor(QPalette.Button, QColor(26, 29, 36))
        palette.setColor(QPalette.ButtonText, QColor(235, 240, 243))
        palette.setColor(QPalette.Highlight, QColor(49, 132, 255))
        palette.setColor(QPalette.HighlightedText, Qt.white)
        self.setPalette(palette)
        self.setStyleSheet(
            "QWidget{background:#0b0d11;color:#e9ecef;}"
            "QGroupBox{border:1px solid #1f2933;border-radius:6px;margin-top:8px;padding:8px;}"
            "QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QTextEdit{background:#0f1116;border:1px solid #1f2933;border-radius:6px;}"
            "QPushButton{background:#1c7ed6;color:white;border-radius:6px;padding:6px 12px;font-weight:600;}"
            "QPushButton:disabled{background:#343a40;color:#adb5bd;}"
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
