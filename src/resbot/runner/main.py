from .config import read_env_config
from .orchestrator import run_orchestration


def main() -> None:
	"""CLI entrypoint for the resbot runner."""
	cfg = read_env_config()
	run_orchestration(cfg)


if __name__ == "__main__":
	main()


