from __future__ import annotations

import argparse
import json

from mercado_financeiro.pit.cvm import (
    audit_dfp_composition_capital,
    audit_fre_capital_social,
    available_asof,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fre", required=True)
    parser.add_argument("--dfp", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--asof", action="append", default=[])
    args = parser.parse_args()

    fre, fre_audit = audit_fre_capital_social(args.fre, args.year)
    dfp, dfp_audit = audit_dfp_composition_capital(args.dfp, args.year)
    payload = {
        "fre": fre_audit.__dict__,
        "dfp": dfp_audit.__dict__,
        "availability": {},
    }
    for date in args.asof:
        payload["availability"][date] = {
            "fre_companies": available_asof(fre, date)["CNPJ_Companhia"].nunique(),
            "dfp_companies": available_asof(dfp, date)["CNPJ_CIA"].nunique(),
        }
    print(json.dumps(payload, default=str, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
