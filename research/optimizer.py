from typing import (Callable, Iterable, Dict, Tuple, List, Optional, Any,
                    Sequence, Literal, Union)

import pandas as pd  # type: ignore
import matplotlib.pyplot as plt  # type: ignore
import seaborn as sns  # type: ignore

from pyfolio.timeseries import perf_stats  # type: ignore

from vector_backtester import perf, sig_pos


class Optimizer:
    """
    Backtest performance of func with parameters sp_1 and sp_2 over
    prices in df.

    Optimizer object will run the backtests on instantiation and make
    results available as properties.

    Args:
    -----

    df - must have columns 'open' and 'close' (signal is generated on
    close, transactions executed on next open)

    func - must take exactly two parameters and return a continuous
    signal (transaction will be executed when signal changes, on index
    point subsequent to the change)

    sp_1 and sp_2 - given as tuples (start, step, mode), where mode is
    either 'geo' for geometric progression or 'lin' for linear
    progression, by default: 'geo'.  For 'geo' mode, if start is an
    int, progression elements will also be cast into int.

    slip - transaction cost expressed as percentage of ticksize

    pairs - pairs of parameters to run the backtest on, if given, sp_1
    and sp_2 will be ignored

    Properties:
    -----------

    corr - correlation between returns of various backtests

    rank - 20 best backtests ranked by total returns

    return_mean - mean annual return of all backtests

    return_median - median of annual return of all backtests

    combine_stats - stats for a strategy that's equal weight
    combination of all backtests

    combine_paths - return path of all backtestest equal weighted
    """

    def __init__(self, df: pd.DataFrame, func: Callable,
                 sp_1: Tuple[Any, ...] = (100, 1.25, 'geo'),
                 sp_2: Tuple[Any, ...] = (.1, .1, 'lin'),
                 slip=1.5,
                 pairs: Optional[Sequence[Tuple[float, float]]] = None
                 ) -> None:

        assert pairs or (sp_1 and sp_2), 'Either pairs or parameters required'

        self.func = func
        self.df = df
        self.slip = slip

        self.raw_stats: Dict[Tuple[float, float], pd.Series] = {}
        self.raw_dailys: Dict[Tuple[float, float], pd.DataFrame] = {}
        self.raw_positions: Dict[Tuple[float, float], pd.DataFrame] = {}
        self.raw_dfs: Dict[Tuple[float, float], pd.DataFrame] = {}

        self.pairs = pairs or self.get_pairs(
            self.progression(sp_1), self.progression(sp_2))

        self._table: Dict[str, pd.DataFrame] = {}

        for p in self.pairs:
            self.calc(p[0], p[1])

        self.extract_stats()
        self.__dict__.update(self._table)
        self.extract_dailys()

    @staticmethod
    def progression(sp: Tuple[Any, ...]) -> Sequence:
        if len(sp) == 3:
            start, step, mode = sp
        elif len(sp) == 2:
            start, step = sp
            mode = 'geo'
        else:
            raise ValueError(
                f'Wrong parameter: {sp}. '
                f'Must be a tuple of: (start, stop, [mode])')

        if isinstance(start, Sequence):
            return start

        if mode == 'geo':
            _t = tuple((start * step**i) for i in range(10))
            if isinstance(start, int):
                return tuple(int(i) for i in _t)
            else:
                return _t
        elif mode == 'lin':
            return tuple(round(start + step*i, 5) for i in range(10))
        else:
            raise ValueError(f"Wrong mode: {mode}, "
                             f"should be 'lin' for linear or 'geo' for "
                             f"geometric")

    @staticmethod
    def get_pairs(sp_1: Iterable[float], sp_2: Iterable[float],
                  ) -> Sequence[Tuple[float, float]]:

        return [(p_1, p_2) for p_1 in sp_1 for p_2 in sp_2]

    def calc(self, p_1: float, p_2: float) -> None:
        data = sig_pos(self.func(self.df['close'], p_1, p_2))
        out = perf(self.df['open'], data, slippage=self.slip)
        self.raw_stats[p_1, p_2] = out.stats
        self.raw_dailys[p_1, p_2] = out.daily
        self.raw_positions[p_1, p_2] = out.positions
        self.raw_dfs[p_1, p_2] = out.df

    def extract_stats(self) -> None:
        self._fields = [i for i in self.raw_stats[self.pairs[-1]].index]
        self.field_trans = {i: i.lower().replace(
            ' ', '_').replace('/', '_').replace('.', '') for i in self._fields}
        self.fields = list(self.field_trans.values())
        self._table = {f: pd.DataFrame() for f in self.fields}
        for index, stats_table in self.raw_stats.items():
            for field in self._fields:
                self._table[self.field_trans[field]
                            ].loc[index] = stats_table[field]

    def extract_dailys(self) -> None:
        log_returns = {}
        returns = {}
        paths = {}
        for k, v in self.raw_dailys.items():
            log_returns[k] = v['lreturn']
            returns[k] = v['returns']
            paths[k] = v['balance']
        self.log_returns = pd.DataFrame(log_returns)
        self.returns = pd.DataFrame(returns)
        self.paths = pd.DataFrame(paths)

    @property
    def corr(self) -> pd.DataFrame:
        return self.log_returns.corr()

    @property
    def rank(self) -> pd.Series:
        return self.paths.iloc[-1].sort_values().tail(20)

    @property
    def return_mean(self) -> float:
        return self._table['annual_return'].mean().mean()

    @property
    def return_median(self) -> float:
        return self._table['annual_return'].stack().median()

    @property
    def combine(self):
        return self.returns.mean(axis=1)

    @property
    def combine_stats(self):
        return perf_stats(self.combine)

    @property
    def combine_paths(self):
        return (self.combine + 1).cumprod()

    def __repr__(self):
        return f'{self.__class__.__name__} for {self.func.__name__}'

    def __str__(self):
        return f"TWo param simulation for {self.func.__name__}"


def plot_grid(data: Optimizer, fields: List[str] = [
        'annual_return', 'sharpe_ratio']) -> None:

    if isinstance(fields, str):
        fields = ['annual_return', fields]

    assert isinstance(fields, Sequence
                      ), f'{fields} is neither string nor sequence'

    assert set(fields).issubset(set(data.fields)), (
        f'Wrong field. '
        f'Allowed fields are: {data.fields}')

    table_one = getattr(data, fields[0])
    table_two = getattr(data, fields[1])
    pos_rows = table_one[table_one > 0].count()/table_one.count()
    pos_columns = table_one[table_one > 0].count(
        axis=1)/table_one.count(axis=1)

    sns.set_style('whitegrid')
    colormap = sns.diverging_palette(10, 133, n=5, as_cmap=True)
    widths = [1, 1, 1, 10, 10, 1, 1]
    heights = [10, 1, 1, 1]
    fig = plt.figure(figsize=(22, 12))
    gs = fig.add_gridspec(4, 7, width_ratios=widths, height_ratios=heights)

    heatmap_kwargs = {'square': True, 'cmap': colormap, 'annot': True,
                      'annot_kws': {'fontsize': 'large'},
                      'fmt': ".2f", 'cbar': False, 'linewidth': .3, }
    no_labels = {'xticklabels': False, 'yticklabels': False}

    if fields[0] == 'annual_return':
        table_1_scaling_kwargs = {'vmin': -.3, 'vmax': .3}
    else:
        table_1_scaling_kwargs = {'robust': True}

    if fields[1] == 'sharpe_ratio':
        table_2_scaling_kwargs = {'vmin': -1, 'vmax': 1}
    else:
        table_2_scaling_kwargs = {'robust': True}

    ax0 = fig.add_subplot(gs[0, 0])
    ax0.set_title('%>0')
    sns.heatmap(pd.DataFrame(pos_columns), **heatmap_kwargs,
                **no_labels, vmin=0, vmax=1, center=.5)

    ax1 = fig.add_subplot(gs[0, 1])
    ax1.set_title('mean')
    sns.heatmap(pd.DataFrame(table_one.mean(axis=1)), **
                heatmap_kwargs, **no_labels, **table_1_scaling_kwargs)

    ax15 = fig.add_subplot(gs[0, 2])
    ax15.set_title('median')
    sns.heatmap(pd.DataFrame(table_one.median(axis=1)), **
                heatmap_kwargs, **no_labels, **table_1_scaling_kwargs)

    ax2 = fig.add_subplot(gs[0, 3])
    ax2.set_title(fields[0])
    sns.heatmap(table_one, **heatmap_kwargs, **table_1_scaling_kwargs)

    ax3 = fig.add_subplot(gs[0, 4])
    ax3.set_title(fields[1])
    sns.heatmap(table_two, **heatmap_kwargs, **table_2_scaling_kwargs)

    ax35 = fig.add_subplot(gs[0, 5])
    ax35.set_title('median')
    sns.heatmap(pd.DataFrame(table_two.median(axis=1)), **
                heatmap_kwargs, **no_labels, **table_2_scaling_kwargs)

    ax4 = fig.add_subplot(gs[0, 6])
    ax4.set_title('mean')
    sns.heatmap(pd.DataFrame(table_two.mean(axis=1)), **
                heatmap_kwargs, **no_labels, **table_2_scaling_kwargs)

    ax45 = fig.add_subplot(gs[1, 3])
    ax45.set_title('median')
    sns.heatmap(pd.DataFrame(table_one.median()).T, **
                heatmap_kwargs, **no_labels, **table_1_scaling_kwargs)

    ax455 = fig.add_subplot(gs[1, 4])
    sns.heatmap(pd.DataFrame(table_two.median()).T, **
                heatmap_kwargs, **no_labels, **table_2_scaling_kwargs)
    ax455.set_title('median')

    ax5 = fig.add_subplot(gs[2, 3])
    ax5.set_title('mean')
    sns.heatmap(pd.DataFrame(table_one.mean()).T, **heatmap_kwargs,
                **no_labels, **table_1_scaling_kwargs)

    ax6 = fig.add_subplot(gs[2, 4])
    sns.heatmap(pd.DataFrame(table_two.mean()).T, **heatmap_kwargs,
                **no_labels, **table_2_scaling_kwargs)
    ax6.set_title('mean')

    ax7 = fig.add_subplot(gs[3, 3])
    ax7.set_title('%>0')
    sns.heatmap(pd.DataFrame(pos_rows).T, **heatmap_kwargs,
                **no_labels, vmin=0, vmax=1, center=.5)