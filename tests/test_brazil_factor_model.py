import numpy as np
import pandas as pd

from mercado_financeiro.research.brazil_factor_model import fit_brazil_factor_model


def test_brazil_factor_model_recovers_known_exposures():
    index = pd.date_range("2026-01-01", periods=60, freq="B")
    market = np.linspace(-0.02, 0.02, len(index))
    smb = np.sin(np.linspace(0, 5, len(index))) * 0.01
    factors = pd.DataFrame({"Rm-Rf": market, "SMB": smb}, index=index)
    asset = pd.Series(0.001 + 1.2 * market - 0.4 * smb, index=index)
    result = fit_brazil_factor_model(asset, factors, factor_columns=("Rm-Rf", "SMB"))
    assert abs(result.alpha_daily - 0.001) < 1e-10
    assert abs(result.betas["Rm-Rf"] - 1.2) < 1e-10
    assert abs(result.betas["SMB"] + 0.4) < 1e-10
    assert result.r_squared > 0.999999
