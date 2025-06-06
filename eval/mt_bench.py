# type: ignore
# pylint: disable=import-outside-toplevel,import-error

from typing import NamedTuple, Optional

from kfp.dsl import component

from utils.consts import RHELAI_IMAGE


@component(base_image=RHELAI_IMAGE, install_kfp_package=False)
def run_mt_bench_op(
    merge_system_user_message: bool,
    # generate_answers,judgment uses a magic word for its mt_bench evaluator  - 'auto'
    # with 'auto', number of gpus allocated for serving is calculated based on environment
    # https://github.com/instructlab/eval/blob/main/src/instructlab/eval/mt_bench.py#L36
    max_workers: str,
    models_folder: str,
    output_path: str = "/output/mt_bench_data.json",
    judge_secret_name: str = None,
) -> NamedTuple("outputs", best_model=str, best_score=float):
    import base64
    import json
    import os
    import ssl
    import subprocess

    import httpx
    import requests
    import torch
    from instructlab.eval.mt_bench import MTBenchEvaluator

    def fetch_secret(secret_name, keys):
        # Kubernetes API server inside the cluster
        K8S_API_SERVER = "https://kubernetes.default.svc"
        NAMESPACE_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
        TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"

        # Fetch namespace
        try:
            with open(NAMESPACE_PATH, "r") as f:
                namespace = f.read().strip()
        except FileNotFoundError:
            raise RuntimeError("Error reading namespace")

        # Fetch service account token
        try:
            with open(TOKEN_PATH, "r") as f:
                token = f.read().strip()
        except FileNotFoundError:
            raise RuntimeError("Error reading service account token")

        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        verify_tls = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        url = f"{K8S_API_SERVER}/api/v1/namespaces/{namespace}/secrets/{secret_name}"
        response = requests.get(url, headers=headers, verify=verify_tls)

        if response.status_code == 200:
            print(f"Successfully fetched secret {secret_name}")
            secret_data = response.json().get("data", {})
            values = []
            for key in keys:
                if key in secret_data:
                    values.append(base64.b64decode(secret_data[key]).decode())
            return values
        else:
            raise RuntimeError(
                f"Error fetching secret: {response.status_code} {response.text}"
            )

    # Use the default SSL context since it leverages OpenSSL to use the correct CA bundle.
    judge_http_client = httpx.Client(verify=ssl.create_default_context())

    if judge_secret_name is None:
        judge_api_key = os.getenv("JUDGE_API_KEY", "")
        judge_model_name = os.getenv("JUDGE_NAME")
        judge_endpoint = os.getenv("JUDGE_ENDPOINT")
    else:
        print("Eval Judge secret specified, fetching...")
        judge_api_key, judge_model_name, judge_endpoint = fetch_secret(
            judge_secret_name, ["api_token", "model_name", "endpoint"]
        )
        print("Eval Judge secret data retrieved.")

    def launch_vllm(
        model_path: str, gpu_count: int, retries: int = 120, delay: int = 10
    ) -> tuple:
        import subprocess
        import sys
        import time

        import requests
        from instructlab.model.backends.common import free_tcp_ipv4_port

        free_port = free_tcp_ipv4_port("127.0.0.1")
        port = str(free_port)
        vllm_server = f"http://127.0.0.1:{port}/v1"

        command = [
            sys.executable,
            "-m",
            "vllm.entrypoints.openai.api_server",
            "--port",
            port,
            "--model",
            model_path,
        ]
        if gpu_count > 0:
            command += [
                "--tensor-parallel-size",
                str(gpu_count),
            ]

        process = subprocess.Popen(args=command)

        print(f"Waiting for vLLM server to start at {vllm_server}...")

        for attempt in range(retries):
            try:
                response = requests.get(f"{vllm_server}/models")
                if response.status_code == 200:
                    print(f"vLLM server is up and running at {vllm_server}.")
                    return process, vllm_server
            except requests.ConnectionError:
                pass

            print(
                f"Server not available yet, retrying in {delay} seconds (Attempt {attempt + 1}/{retries})..."
            )
            time.sleep(delay)

        raise RuntimeError(
            f"Failed to start vLLM server at {vllm_server} after {retries} retries."
        )

    def shutdown_vllm(process: subprocess.Popen, timeout: int = 20):
        import subprocess

        from instructlab.model.backends.vllm import wait_for_stable_vram

        try:
            process.terminate()
            process.wait(timeout=timeout)

            if process.poll() is None:
                print(f"Forcefully killing vLLM server process with PID: {process.pid}")
                process.kill()

            print(f"Successfully stopped vLLM server with PID: {process.pid}")

        except subprocess.TimeoutExpired:
            print(
                f"Timeout expired. Forcefully killing vLLM server with PID: {process.pid}"
            )
            process.kill()  # Force kill the process if over timeout
        except Exception as e:
            print(f"Failed to stop process with PID {process.pid}. Error: {e}")
        # Note from instructlab/model/backends/vllm.py
        # vLLM relies on stable VRAM,  residual reclamation activity
        # can lead to crashes on restart. To prevent this add a
        # short delay (typically ~ 10 seconds, max 30) to verify stability.
        wait_for_stable_vram(30)

    gpu_available = torch.cuda.is_available()
    gpu_name = (
        torch.cuda.get_device_name(torch.cuda.current_device())
        if gpu_available
        else "No GPU available"
    )
    gpu_count = torch.cuda.device_count() if gpu_available else 0

    print(f"GPU Available: {gpu_available}, {gpu_name}")

    models_list = os.listdir(models_folder)

    scores = {}
    all_mt_bench_data = []

    # generate_answers,judgment uses a magic word for its mt_bench evaluator  - 'auto'
    # with 'auto', number of gpus allocated for serving is calculated based on environment
    # https://github.com/instructlab/eval/blob/main/src/instructlab/eval/mt_bench.py#L36
    if max_workers == "auto":
        try:
            usable_cpu_count = len(os.sched_getaffinity(0)) // 2
        except AttributeError:
            import multiprocessing

            usable_cpu_count = multiprocessing.cpu_count() // 2
        max_workers = usable_cpu_count

    # modify model_list to ignore any jsonl files present in the directory
    models_list = [model for model in models_list if not model.endswith(".jsonl")]
    for model_name in models_list:
        print(f"Serving candidate model: {model_name}")
        model_path = f"{models_folder}/{model_name}"

        vllm_process, vllm_server = launch_vllm(model_path, gpu_count)

        # model ID is the model_path value in vLLM
        evaluator = MTBenchEvaluator(
            model_name=model_path,
            judge_model_name=judge_model_name,
            output_dir="/tmp/eval_output",
            merge_system_user_message=merge_system_user_message,
        )

        evaluator.gen_answers(
            server_url=vllm_server,
            serving_gpus=gpu_count,
            max_workers=max_workers,
            http_client=judge_http_client,
        )

        shutdown_vllm(vllm_process)

        overall_score, qa_pairs, turn_scores, error_rate = evaluator.judge_answers(
            server_url=judge_endpoint,
            api_key=judge_api_key,
            serving_gpus=gpu_count,
            max_workers=max_workers,
            http_client=judge_http_client,
        )

        mt_bench_data = {
            "report_title": "SKILLS EVALUATION REPORT",
            "model": model_path,
            "judge_model": judge_model_name,
            "overall_score": overall_score,
            "turn_scores": turn_scores,
            "qa_scores": qa_pairs,
            "error_rate": error_rate,
        }

        all_mt_bench_data.append(mt_bench_data)
        scores[model_path] = overall_score

    outputs = NamedTuple("outputs", best_model=str, best_score=float)
    best_model = max(scores, key=scores.get)
    best_score = scores[best_model]
    mt_bench_report = {
        "best_model": best_model,
        "best_score": best_score,
        "reports": all_mt_bench_data,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(mt_bench_report, f, indent=4)

    # Rename the best model directory to "candidate_model" for the next step
    # So we know which model to use for the final evaluation
    if os.path.exists(os.path.join(models_folder, "candidate_model")):
        print("candidate_model already exists. Skipping renaming")
    else:
        os.rename(
            os.path.join(models_folder, best_model),
            os.path.join(models_folder, "candidate_model"),
        )

    return outputs(best_model=best_model, best_score=best_score)
