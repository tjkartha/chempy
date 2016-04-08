# -*- coding: utf-8 -*-
"""
This module contains functions for formulating systems of Ordinary Differential
Equations (ODE-systems) which may be integrated numerically to model temporal
evolution of concentrations in reaction systems.
"""
from __future__ import (absolute_import, division, print_function)

import numpy as np

from chempy.units import get_derived_unit, to_unitless

from .rates import _RateExpr, MassAction, law_of_mass_action_rates


def dCdt(rsys, rates):
    """ Returns a list of the time derivatives of the concentrations

    Parameters
    ----------
    rsys: ReactionSystem instance
    rates: array_like
        rates (to be weighted by stoichiometries) of the reactions
        in ``rsys``

    Examples
    --------
    >>> from chempy import ReactionSystem, Reaction
    >>> line, keys = 'H2O -> H+ + OH- ; 1e-4', 'H2O H+ OH-'
    >>> rsys = ReactionSystem([Reaction.from_string(line, keys)], keys)
    >>> dCdt(rsys, [0.0054])
    [-0.0054, 0.0054, 0.0054]

    """
    f = [0]*rsys.ns
    net_stoichs = rsys.net_stoichs()
    for idx_s in range(rsys.ns):
        for idx_r in range(rsys.nr):
            f[idx_s] += net_stoichs[idx_r, idx_s]*rates[idx_r]
    return f


class _Always(object):
    __slots__ = ('value')

    def __init__(self, value):
        self.value = value

    def __getitem__(self, key):
        return self.value


def get_odesys(rsys, include_params=False, SymbolicSys=None,
               unit_registry=None, output_conc_unit=None,
               output_time_unit=None, state=None, **kwargs):
    """ Creates a :class:`pyneqsys.SymbolicSys` from a :class:`ReactionSystem`

    Parameters
    ----------
    rsys: ReactionSystem
    include_params: bool (default: False)
        whether rate constants should be included into the rate expressions or
        left as free parameters in the :class:`pyneqsys.SymbolicSys` instance.
    SymbolicSys: class (optional)
        default: :class:`pyneqsys.SymbolicSys`
    unit_registry: dict (optional)
        see :func:`chempy.units.get_derived_units`
    output_conc_unit: unit (Optional)
    output_time_unit: unit (Optional)
    state: object (optional)
        argument for reaction parameters
    \*\*kwargs:
        Keyword arguemnts pass on to `SymbolicSys`

    """
    if SymbolicSys is None:
        from pyodesys.symbolic import SymbolicSys

    if 'names' not in kwargs:
        kwargs['names'] = list(rsys.substances.keys())

    if unit_registry is not None:
        # We need to make rsys_params unitless and create
        # a post- & pre-processor for SymbolicSys
        time_unit = get_derived_unit(unit_registry, 'time')
        conc_unit = get_derived_unit(unit_registry, 'concentration')
        p_units = list(law_of_mass_action_rates(_Always(1/conc_unit), rsys,
                                                _Always(conc_unit/time_unit), state))
        rsys_params = [elem(state) if callable(elem) else to_unitless(elem, p_unit) for elem, p_unit
                       in zip(rsys.params(), p_units)]

        def pre_processor(x, y, p):
            return to_unitless(x, time_unit), to_unitless(y, conc_unit), [
                to_unitless(elem, p_unit) for elem, p_unit in zip(p, p_units)]

        def post_processor(x, y, p):
            time = x*time_unit
            if output_time_unit is not None:
                time = time.rescale(output_time_unit)
            conc = y*conc_unit
            if output_conc_unit is not None:
                conc = conc.rescale(output_conc_unit)
            return time, conc, [elem*p_unit for elem, p_unit
                                in zip(p, p_units)]
        kwargs['pre_processors'] = [pre_processor]
        kwargs['post_processors'] = [post_processor]
    else:
        rsys_params = rsys.params()

    _nscalars = [rxn.param.nargs if isinstance(rxn.param, _RateExpr) else 1 for
                 rxn in rsys.rxns]
    _accum_n_params = np.cumsum([0]+_nscalars)

    def dydt(t, y, p):
        rates = []
        for ri, rxn in enumerate(rsys.rxns):
            param = rxn.param
            if not hasattr(param, 'eval'):
                param = MassAction([param])  # default
            # id0 = _accum_n_params[ri]
            # id1 = _accum_n_params[ri+1]
            # rsys_params[id0:id1]
            rates.append(param.eval(rsys, ri, y, None))
        return dCdt(rsys, rates)

    return SymbolicSys.from_callback(
        dydt, rsys.ns, 0 if include_params else rsys.nr, **kwargs)
