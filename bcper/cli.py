import argparse
import sys

from .client import Client


def _ok(resp):
    if not resp.get("ok"):
        print(f"Error: {resp.get('error')}", file=sys.stderr)
        sys.exit(1)
    return resp.get("data")


def cmd_item_list(args):
    client = Client()
    data = _ok(client.list_items())
    for item in data:
        enc = "🔒" if item.get("password") else " "
        print(f"  {enc} {item['key']}: {', '.join(item['paths'])}")


def cmd_item_add(args):
    client = Client()
    data = _ok(client.add_item(
        key=args.key,
        paths=args.paths,
        password=args.password,
        bcpignore=args.ignore or [],
    ))
    print(f"Added item: {data['key']}")


def cmd_item_delete(args):
    client = Client()
    _ok(client.delete_item(args.key))
    print(f"Deleted item: {args.key}")


def cmd_vault_list(args):
    client = Client()
    data = _ok(client.list_vaults())
    for vault in data:
        enc = "🔒" if vault.get("password") else " "
        print(f"  {enc} {vault['name']}: {', '.join(vault['item_keys'])}")


def cmd_vault_add(args):
    client = Client()
    data = _ok(client.add_vault(
        name=args.name,
        item_keys=args.items,
        password=args.password,
        bcpignore=args.ignore or [],
    ))
    print(f"Added vault: {data['name']}")


def cmd_vault_delete(args):
    client = Client()
    _ok(client.delete_vault(args.name))
    print(f"Deleted vault: {args.name}")


def cmd_store_list(args):
    client = Client()
    data = _ok(client.list_stores())
    for name, cfg in data.items():
        print(f"  {name} ({cfg['type']}): {cfg.get('path', cfg.get('remote', ''))}")


def cmd_store_add(args):
    client = Client()
    data = _ok(client.add_store(name=args.name, type=args.type, path=args.path, remote=args.remote))
    print(f"Added store: {data['name']}")


def cmd_store_delete(args):
    client = Client()
    _ok(client.delete_store(args.name))
    print(f"Deleted store: {args.name}")


def cmd_freq_list(args):
    client = Client()
    data = _ok(client.list_frequencies())
    for freq in data:
        print(f"  {freq['id']}: {freq['name']} ({freq['period_type']}, interval={freq['interval']})")


def cmd_freq_add(args):
    client = Client()
    data = _ok(client.add_frequency(
        id=args.id,
        name=args.name,
        period_type=args.period_type,
        interval=args.interval,
    ))
    print(f"Added frequency: {data['id']}")


def cmd_freq_delete(args):
    client = Client()
    _ok(client.delete_frequency(args.id))
    print(f"Deleted frequency: {args.id}")


def cmd_job_list(args):
    client = Client()
    data = _ok(client.list_jobs())
    for job in data:
        status = "✅" if job.get("enabled") else "❌"
        print(f"  {status} {job['id']}: {job['name']} → {job['target_type']}:{job['target_name']} @ {job['store_name']} (freq={job['frequency_id']})")


def cmd_job_add(args):
    client = Client()
    data = _ok(client.add_job(
        name=args.name,
        target_type=args.target_type,
        target_name=args.target_name,
        store_name=args.store_name,
        frequency_id=args.frequency_id,
    ))
    print(f"Added job: {data['id']}")


def cmd_job_delete(args):
    client = Client()
    _ok(client.delete_job(args.id))
    print(f"Deleted job: {args.id}")


def cmd_job_run(args):
    client = Client()
    data = _ok(client.backup(args.target_type, args.target_name, args.store_name))
    print(f"Backup created: {data['archive']}")


def cmd_backup_list(args):
    client = Client()
    data = _ok(client.list_backups(args.store))
    for name in data:
        print(f"  {name}")


def cmd_restore(args):
    client = Client()
    data = _ok(client.restore(
        archive=args.archive,
        store_name=args.store,
        password=args.password,
        target_dir=args.target_dir,
    ))
    print(f"Restored to: {data['target_dir']}")
    if data.get("warnings"):
        for w in data["warnings"]:
            print(f"  Warning: {w}")


def main():
    parser = argparse.ArgumentParser(prog="bcper", description="BCPER CLI")
    sub = parser.add_subparsers(dest="command")

    # item
    item_p = sub.add_parser("item", help="Manage backup items")
    item_sub = item_p.add_subparsers(dest="item_cmd")
    item_sub.add_parser("list", help="List items")
    p = item_sub.add_parser("add", help="Add item")
    p.add_argument("key")
    p.add_argument("paths", nargs="+")
    p.add_argument("--password")
    p.add_argument("--ignore", action="append")
    item_sub.add_parser("delete", help="Delete item").add_argument("key")

    # vault
    vault_p = sub.add_parser("vault", help="Manage vaults")
    vault_sub = vault_p.add_subparsers(dest="vault_cmd")
    vault_sub.add_parser("list", help="List vaults")
    p = vault_sub.add_parser("add", help="Add vault")
    p.add_argument("name")
    p.add_argument("--items", nargs="+", required=True)
    p.add_argument("--password")
    p.add_argument("--ignore", action="append")
    vault_sub.add_parser("delete", help="Delete vault").add_argument("name")

    # store
    store_p = sub.add_parser("store", help="Manage stores")
    store_sub = store_p.add_subparsers(dest="store_cmd")
    store_sub.add_parser("list", help="List stores")
    p = store_sub.add_parser("add", help="Add store")
    p.add_argument("name")
    p.add_argument("--type", choices=["local", "rclone"], default="local")
    p.add_argument("--path", default="~/backups")
    p.add_argument("--remote")
    store_sub.add_parser("delete", help="Delete store").add_argument("name")

    # frequency
    freq_p = sub.add_parser("frequency", help="Manage frequencies")
    freq_sub = freq_p.add_subparsers(dest="freq_cmd")
    freq_sub.add_parser("list", help="List frequencies")
    p = freq_sub.add_parser("add", help="Add frequency")
    p.add_argument("id")
    p.add_argument("name")
    p.add_argument("--period-type", choices=["once", "hourly", "daily"], default="once")
    p.add_argument("--interval", type=int, default=1)
    freq_sub.add_parser("delete", help="Delete frequency").add_argument("id")

    # job
    job_p = sub.add_parser("job", help="Manage jobs")
    job_sub = job_p.add_subparsers(dest="job_cmd")
    job_sub.add_parser("list", help="List jobs")
    p = job_sub.add_parser("add", help="Add job")
    p.add_argument("--name", required=True)
    p.add_argument("--target-type", choices=["item", "vault"], required=True)
    p.add_argument("--target-name", required=True)
    p.add_argument("--store-name", required=True)
    p.add_argument("--frequency-id", required=True)
    job_sub.add_parser("delete", help="Delete job").add_argument("id")
    p = job_sub.add_parser("run", help="Run backup now")
    p.add_argument("--target-type", choices=["item", "vault"], required=True)
    p.add_argument("--target-name", required=True)
    p.add_argument("--store-name", required=True)

    # backup
    backup_p = sub.add_parser("backup", help="Backup operations")
    backup_sub = backup_p.add_subparsers(dest="backup_cmd")
    p = backup_sub.add_parser("list", help="List backups")
    p.add_argument("store")
    p = backup_sub.add_parser("restore", help="Restore backup")
    p.add_argument("archive")
    p.add_argument("store")
    p.add_argument("--password")
    p.add_argument("--target-dir")

    args = parser.parse_args()

    if args.command == "item":
        if args.item_cmd == "list":
            cmd_item_list(args)
        elif args.item_cmd == "add":
            cmd_item_add(args)
        elif args.item_cmd == "delete":
            cmd_item_delete(args)
    elif args.command == "vault":
        if args.vault_cmd == "list":
            cmd_vault_list(args)
        elif args.vault_cmd == "add":
            cmd_vault_add(args)
        elif args.vault_cmd == "delete":
            cmd_vault_delete(args)
    elif args.command == "store":
        if args.store_cmd == "list":
            cmd_store_list(args)
        elif args.store_cmd == "add":
            cmd_store_add(args)
        elif args.store_cmd == "delete":
            cmd_store_delete(args)
    elif args.command == "frequency":
        if args.freq_cmd == "list":
            cmd_freq_list(args)
        elif args.freq_cmd == "add":
            cmd_freq_add(args)
        elif args.freq_cmd == "delete":
            cmd_freq_delete(args)
    elif args.command == "job":
        if args.job_cmd == "list":
            cmd_job_list(args)
        elif args.job_cmd == "add":
            cmd_job_add(args)
        elif args.job_cmd == "delete":
            cmd_job_delete(args)
        elif args.job_cmd == "run":
            cmd_job_run(args)
    elif args.command == "backup":
        if args.backup_cmd == "list":
            cmd_backup_list(args)
        elif args.backup_cmd == "restore":
            cmd_restore(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
