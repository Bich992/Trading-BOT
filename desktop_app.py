import sys
import datetime as dt

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QComboBox, QPushButton,
    QTextEdit, QSplitter, QCheckBox, QGroupBox,
    QFormLayout, QLineEdit, QMessageBox, QSpinBox, QDoubleSpinBox
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QObject

import pandas as pd

from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar

from charts.chart_widget import ChartWidget
from charts.recap_widget import RecapWidget
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Trading Bot – AUTO Multi-Asset + Legs (PAPER)")
        self.resize(1900, 1080)

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

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_center_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([420, 980, 450])

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.addWidget(splitter)
        self.setCentralWidget(root)

        self._refresh_portfolio_view()
        self._refresh_trade_history()
        self._refresh_positions_list()
        self._refresh_watchlist()
        self._refresh_recap()

    # ---------------- LEFT ----------------
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
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        chart_panel = QWidget()
        layout = QVBoxLayout(chart_panel)

        header = QHBoxLayout()
        self.lbl_asset = QLabel("Selected asset: —")
        self.lbl_asset.setStyleSheet("font-size:18px;font-weight:700;")
        header.addWidget(self.lbl_asset)

        self.lbl_tf_auto = QLabel("TF auto: —")
        self.lbl_tf_auto.setStyleSheet("color:#0b7285;font-weight:600;")
        header.addWidget(self.lbl_tf_auto)

        header.addStretch()

        self.cmb_tf = QComboBox()
        self.cmb_tf.addItems(TIMEFRAMES)
        self.cmb_tf.setCurrentText(self.current_tf)
        self.cmb_tf.currentTextChanged.connect(self._change_tf)
        header.addWidget(QLabel("Chart TF"))
        header.addWidget(self.cmb_tf)

        self.btn_refresh = QPushButton("Refresh Chart")
        self.btn_refresh.clicked.connect(self._refresh_chart)
        header.addWidget(self.btn_refresh)

        zoom_hint = QLabel("Scroll on chart to zoom / drag toolbar to pan")
        zoom_hint.setStyleSheet("color:#666;font-size:12px;")
        header.addWidget(zoom_hint)

        layout.addLayout(header)

        self.chart = ChartWidget()
        self.toolbar = NavigationToolbar(self.chart, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.chart, 6)

        config_splitter = QSplitter(Qt.Vertical)
        config_splitter.setChildrenCollapsible(False)

        # AUTO Multi-asset config
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
        f.addRow("Interval (sec)", self.sp_interval)
        f.addRow("Conf entry", self.sp_conf_entry)
        f.addRow("Conf add", self.sp_conf_add)
        f.addRow("Max open assets", self.sp_max_assets)
        f.addRow("Cooldown (sec)", self.sp_cooldown)
        f.addRow("Add mode", self.cmb_add_mode)
        f.addRow("Max legs/asset", self.sp_max_legs)
        f.addRow(self.chk_short)
        f.addRow("Size mode", self.cmb_size_mode)
        f.addRow("Fixed notional", self.sp_fixed)
        f.addRow("Risk per trade (AUTO_RISK)", self.sp_riskpct)
        f.addRow("Fee rate", self.sp_fee)
        f.addRow("Initial cash", self.sp_cash)
        f.addRow(btn_apply)
        f.addRow(btn_reset)

        config_splitter.addWidget(auto_box)

        stories_box = QWidget()
        s_layout = QVBoxLayout(stories_box)
        s_layout.addWidget(QLabel("Stories"))
        self.txt_stories = QTextEdit()
        self.txt_stories.setReadOnly(True)
        s_layout.addWidget(self.txt_stories, 2)
        config_splitter.addWidget(stories_box)
        config_splitter.setSizes([420, 260])

        splitter.addWidget(chart_panel)
        splitter.addWidget(config_splitter)
        splitter.setSizes([760, 320])
        return splitter

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
        splitter.addWidget(trades_box)
        splitter.addWidget(recap_box)
        splitter.setSizes([260, 260, 420])

        return splitter

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
        self._refresh_chart()
        self._refresh_positions_list()

    # ---------------- Chart ----------------
    def _change_tf(self, tf):
        self.current_tf = tf
        self._refresh_chart()

    def _refresh_chart(self):
        if not self.current_symbol:
            return
        try:
            self.last_df = self.provider.fetch_ohlc(self.current_symbol, self.current_tf, limit=400)
            markers = self.markers_by_symbol.get(self.current_symbol, [])
            tf_info = self.last_tf_scores.get(self.current_symbol)
            if tf_info:
                self.lbl_tf_auto.setText(f"TF auto: {tf_info.timeframe} ({tf_info.regime})")
                chart_title = f"{self.current_symbol} @ {self.current_tf} | best {tf_info.timeframe} ({tf_info.regime})"
            else:
                self.lbl_tf_auto.setText("TF auto: —")
                chart_title = f"{self.current_symbol} @ {self.current_tf}"
            self.chart.plot(
                self.last_df,
                markers=markers,
                ema_list=(self.ema_1, self.ema_2, self.ema_3),
                rsi_period=self.rsi_period,
                macd_params=(self.macd_fast, self.macd_slow, self.macd_sig),
                title=chart_title
            )
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

    def _append_story(self, line: str):
        prev = self.txt_stories.toPlainText().strip()
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        new_line = f"[{stamp}] {line}"
        self.txt_stories.setText((prev + "\n" + new_line).strip() if prev else new_line)

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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
