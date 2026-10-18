"""Explicit training, activation/rollback, and evaluation commands."""
import argparse
from datetime import datetime
import json
from uuid import UUID

from .store import Store
from .models import train_candidate, promote


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamp must include a timezone")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    train = commands.add_parser("train")
    train.add_argument("--service", required=True)
    train.add_argument("--start", type=timestamp, required=True)
    train.add_argument("--end", type=timestamp, required=True)
    train.add_argument("--features", default="cpu_cores,memory_fraction")
    train.add_argument("--healthy", action="store_true", help="Confirm selected period contains representative healthy operation")
    for command in ("promote", "rollback"):
        sub = commands.add_parser(command)
        sub.add_argument("--model", type=UUID, required=True)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--model", type=UUID, required=True)
    evaluate.add_argument("--start", type=timestamp, required=True)
    evaluate.add_argument("--end", type=timestamp, required=True)
    evaluate.add_argument("--reviewed", action="store_true", help="Confirm recorded faults and healthy periods cover the test interval")
    forecasts = commands.add_parser("evaluate-forecasts")
    forecasts.add_argument("--service",required=True)
    forecasts.add_argument("--start",type=timestamp,required=True)
    forecasts.add_argument("--end",type=timestamp,required=True)
    args = parser.parse_args()
    store = Store()
    try:
        if args.command == "train":
            if not args.healthy:
                parser.error("--healthy is required; fault exclusion alone cannot establish healthy data")
            result = train_candidate(store, args.service, args.start, args.end, args.features.split(","))
        elif args.command == "evaluate-forecasts":
            from .evaluation import evaluate_forecasts
            result = evaluate_forecasts(store,args.service,args.start,args.end)
        elif args.command == "evaluate":
            if not args.reviewed:
                parser.error("--reviewed is required; unrecorded faults would invalidate precision/recall")
            from .evaluation import evaluate_model
            result = evaluate_model(store, args.model, args.start, args.end)
        else:
            result = promote(store, args.model)
        print(json.dumps(result, default=str, indent=2))
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")
    finally:
        store.close()


if __name__ == "__main__":
    main()
