from typing import List

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from core.paper_engine import Trade


class RecapWidget(FigureCanvas):
    """Plots virtual-learning recap with equity and cost breakdown."""

    def __init__(self, parent=None):
        self.fig = Figure(figsize=(7, 5), tight_layout=True)
        super().__init__(self.fig)
        self.setParent(parent)

        self.ax_equity = self.fig.add_subplot(2, 1, 1)
        self.ax_costs = self.fig.add_subplot(2, 1, 2, sharex=self.ax_equity)

    def plot(self, trades: List[Trade], starting_cash: float):
        self.ax_equity.clear()
        self.ax_costs.clear()

        if not trades:
            self.ax_equity.text(0.5, 0.5, "Nessuna operazione simulata", ha="center", va="center")
            self.ax_equity.set_axis_off()
            self.ax_costs.set_axis_off()
            self.draw()
            return

        trades_sorted = sorted(trades, key=lambda t: t.ts)
        times = [t.ts for t in trades_sorted]

        cumulative = []
        net = starting_cash
        gross_changes = []
        fee_costs = []

        for t in trades_sorted:
            net += t.pnl_realized
            cumulative.append(net)
            gross_changes.append(t.pnl_realized + t.fee)
            fee_costs.append(-t.fee)

        self.ax_equity.plot(times, cumulative, color="#0b7285", linewidth=2, label="Equity simulata")
        self.ax_equity.set_ylabel("Equity virtuale")
        self.ax_equity.grid(True, linestyle=":", alpha=0.4)
        self.ax_equity.legend(loc="upper left")

        bar_width = 0.012
        self.ax_costs.bar(times, gross_changes, width=bar_width, color="#198754", alpha=0.7, label="Risultato lordo")
        self.ax_costs.bar(times, fee_costs, width=bar_width, color="#dc3545", alpha=0.5, label="Fee / costi")
        self.ax_costs.axhline(0, color="#666", linewidth=1)
        self.ax_costs.grid(True, linestyle=":", alpha=0.4)
        self.ax_costs.set_ylabel("Flussi")
        self.ax_costs.legend(loc="upper left")

        self.fig.autofmt_xdate()
        self.draw()
