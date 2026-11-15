"""Quality-report coverage for the generated transaction CSV."""

from aml.simulator.normal import CSV_FIELDS, summarize_csv


def test_summary_reports_client_type_channel_amount_and_daily_activity(tmp_path) -> None:
    path = tmp_path / "transactions.csv"
    rows = [
        ["tx-00000001", "2027-01-15T01:00:00Z", "acct-000001", "ext-000001", "10.00",
         "MAD", "card", "student", "Rabat"],
        ["tx-00000002", "2027-01-15T13:00:00Z", "acct-000002", "ext-cash", "30.00",
         "MAD", "cash_deposit", "merchant", "Casa"],
        ["tx-00000003", "2027-01-16T13:00:00Z", "acct-000003", "acct-000002", "50.00",
         "MAD", "transfer", "merchant", "Casa"],
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        stream.write(",".join(CSV_FIELDS) + "\n")
        for row in rows:
            stream.write(",".join(row) + "\n")

    report = summarize_csv(path)

    assert report["transactions"] == 3
    assert report["by_profile"] == {"merchant": 2, "student": 1}
    assert report["by_channel"] == {"card": 1, "cash_deposit": 1, "transfer": 1}
    assert report["by_date"] == {"2027-01-15": 2, "2027-01-16": 1}
    assert report["amounts_mad_by_profile"]["merchant"] == {
        "transactions": 2, "min_mad": 30.0, "median_mad": 40.0, "mean_mad": 40.0,
        "p95_mad": 50.0, "max_mad": 50.0,
    }
