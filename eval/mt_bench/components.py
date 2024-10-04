# type: ignore
# pylint: disable=no-value-for-parameter,import-outside-toplevel,import-error
from typing import List, NamedTuple, Optional
from kfp.dsl import component, Input, Output, Artifact, Model, importer
from utils.consts import PYTHON_IMAGE

EVAL_IMAGE = "quay.io/sallyom/instructlab-ocp:eval"


# TODO: package vllm, etc within base image
@component(
    base_image=EVAL_IMAGE,
    packages_to_install=[
        "vllm",
        "git+https://github.com/sallyom/ilab-on-ocp.git@final-eval#subdirectory=utils/helpers",
    ],
)
def run_mt_bench_op(
    models_path_prefix: str,
    mt_bench_output: Output[Artifact],
    merge_system_user_message: bool,
    # generate_answers,judgment uses a magic word for its mt_bench evaluator  - `auto`
    # with `auto`, number of gpus allocated for serving is calculated based on environment
    # https://github.com/instructlab/eval/blob/main/src/instructlab/eval/mt_bench.py#L36
    max_workers: str = "auto",
    models_list: List[str] = None,
    models_folder: Optional[str] = None,
    device: str = None,
) -> NamedTuple("outputs", best_model=str, best_score=float):
    import json
    import torch
    import os

    from instructlab.eval.mt_bench import MTBenchEvaluator
    from helpers import launch_local_vllm, stop_local_vllm, VLLM_SERVER

    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    candidate_server_url = VLLM_SERVER

    gpu_available = torch.cuda.is_available()
    gpu_name = (
        torch.cuda.get_device_name(torch.cuda.current_device())
        if gpu_available
        else "No GPU available"
    )
    gpu_count = torch.cuda.device_count() if gpu_available else 0

    print(f"GPU Available: {gpu_available}, {gpu_name}")

    # See note above about magic word "auto"
    if max_workers == "auto":
        try:
            usable_cpu_count = len(os.sched_getaffinity(0)) // 2
        except AttributeError:
            usable_cpu_count = multiprocessing.cpu_count() // 2
        max_workers = usable_cpu_count

    # TODO: Using evaluator results in connection errors, need to determine why.
    #       For now, using mt_bench_answers.generate_answers & mt_bench_judgment.generate_judgment
    # evaluator = MTBenchEvaluator(
    #    model_name=candidate_model_name,
    #    judge_model_name=judge_model_name,
    #    max_workers=max_workers,
    #    merge_system_user_message=merge_system_user_message
    # )

    if models_list is None and models_folder:
        models_list = os.listdir(models_folder)

    judge_api_key = os.getenv("JUDGE_API_KEY", "")
    judge_model_name = os.getenv("JUDGE_NAME")
    judge_endpoint = os.getenv("JUDGE_ENDPOINT")

    scores = {}
    all_mt_bench_data = []

    for model_name in models_list:
        print(f"Serving candidate model: {model_name}")
        model_path = f"{models_path_prefix}/{model_name}"

        launch_local_vllm(model_path, gpu_count)

        # model ID is the model_path value in vLLM
        print("Generating answers...")
        mt_bench_answers.generate_answers(
            model_name=model_path,
            model_api_base=candidate_server_url,
            output_dir="/tmp/eval_output",
            max_workers=max_workers,
        )

        print("Judging answers...")
        overall_score, qa_pairs, turn_scores, error_rate = (
            mt_bench_judgment.generate_judgment(
                model_name=model_path,
                judge_model_name=judge_model_name,
                model_api_base=judge_endpoint,
                api_key=judge_api_key,
                output_dir="/tmp/eval_output",
                max_workers=max_workers,
                merge_system_user_message=merge_system_user_message,
            )
        )

        stop_local_vllm()

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

    with open(mt_bench_output.path, "w") as f:
        json.dump(all_mt_bench_data, f, indent=4)

    outputs = NamedTuple("outputs", best_model=str, best_score=float)
    best_model = max(scores, key=scores.get)
    best_score = scores[best_model]
    return outputs(best_model=best_model, best_score=best_score)


@component(base_image=PYTHON_IMAGE)
def load_mt_bench_results_op(mt_bench_output: Input[Artifact]) -> list:
    import json

    mt_bench_score_list = []
    with open(mt_bench_output.path, "r") as f:
        mt_bench_score_list = json.load(f)

    print("MT_Bench Evaluation Data:")
    for mt_bench_score in mt_bench_score_list:
        print(json.dumps(mt_bench_score, indent=4))

    return mt_bench_score_list
