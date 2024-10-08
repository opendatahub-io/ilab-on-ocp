# type: ignore
# pylint: disable=no-value-for-parameter,import-outside-toplevel,import-error
from typing import List, NamedTuple

from kfp.dsl import Artifact, Dataset, Input, Model, Output, component, importer

from utils.consts import EVAL_IMAGE, PYTHON_IMAGE


# TODO: update to ilab image, already has vLLM installed
@component(
    base_image=EVAL_IMAGE,
    packages_to_install=[
        "vllm",
    ],
)
def run_final_eval_op(
    mmlu_branch_output: Output[Artifact],
    mt_bench_branch_output: Output[Artifact],
    candidate_model: str,
    base_model_dir: str,
    tasks: Input[Dataset],
    taxonomy: Input[Dataset],
    base_branch: str,
    candidate_branch: str,
    max_workers: str,
    device: str,
    model_dtype: str,
    few_shots: int,
    batch_size: int,
    merge_system_user_message: bool,
):
    import json
    import os

    import torch
    from helpers import (
        VLLM_SERVER,
        launch_vllm,
        stop_vllm,
    )
    from instructlab.eval.mmlu import MMLU_TASKS, MMLUBranchEvaluator
    from instructlab.eval.mt_bench import MTBenchBranchEvaluator
    from instructlab.model.evaluate import qa_pairs_to_qna_to_avg_scores, sort_score

    ######################################################################
    # branch_eval_summary_to_json creates a json object from output of instructlab/eval
    # TODO: Add this to the instructlab/eval or instructlab/instructlab repository
    def branch_eval_summary_to_json(
        improvements: list[tuple[str, float, float, float]],
        regressions: list[tuple[str, float, float, float]],
        no_changes: list[tuple[str, float]],
        new=None,
    ) -> str:
        """Generates a JSON object from the _branch benchmark evaluations"""

        import json

        summary = {"improvements": [], "regressions": [], "no_changes": [], "new": []}

        if len(improvements) > 0:
            improvements.sort(key=sort_score, reverse=True)
            for improvement in improvements:
                task, delta, base_score, new_score = improvement
                summary["improvements"].append(
                    {
                        "task": task,
                        "base_score": round(base_score, 2),
                        "new_score": round(new_score, 2),
                        "delta": delta,
                    }
                )

        if len(regressions) > 0:
            regressions.sort(key=sort_score)
            for regression in regressions:
                task, delta, base_score, new_score = regression
                summary["regressions"].append(
                    {
                        "task": task,
                        "base_score": round(base_score, 2),
                        "new_score": round(new_score, 2),
                        "delta": delta,
                    }
                )

        if len(no_changes) > 0:
            for entry in no_changes:
                task, avg_score = entry
                summary["no_changes"].append(
                    {"task": task, "average_score": round(avg_score, 2)}
                )

        if new is not None and len(new) > 0:
            for entry in new:
                na, avg_score = entry
                summary["new"].append(
                    {"qna": qna, "average_score": round(avg_score, 2)}
                )

        return json.dumps(summary, indent=4)

    ######################################################################

    gpu_available = torch.cuda.is_available()
    gpu_name = (
        torch.cuda.get_device_name(torch.cuda.current_device())
        if gpu_available
        else "No GPU available"
    )
    gpu_count = torch.cuda.device_count() if gpu_available else 0

    print(f"GPU Available: {gpu_available}, Using: {gpu_name}")

    # MMLU_BRANCH

    # find_node_dataset_directories to find sdg output node_datasets_*
    def find_node_dataset_directories(base_directory: str):
        import os
        import re

        # This is specific to ilab/eval output
        pattern = r"node_datasets_"
        matching_dirs = []
        regex = re.compile(pattern)

        for root, dirs, files in os.walk(base_directory):
            for directory in dirs:
                if regex.search(directory):
                    matching_dirs.append(os.path.join(root, directory))

        return matching_dirs

    mmlu_tasks = ["mmlu_pr"]

    node_dataset_dirs = find_node_dataset_directories(tasks.path)
    # This assumes generated filesystem from ilab sdg, which
    # generates a node_datasets_ directory for MMLU custom tasks data
    if node_dataset_dirs:
        tasks_dir = node_dataset_dirs[0]

        mmlu_branch_evaluators = [
            MMLUBranchEvaluator(
                model_path=candidate_model,
                tasks_dir=tasks_dir,
                tasks=mmlu_tasks,
                few_shots=few_shots,
                batch_size=batch_size,
            ),
            MMLUBranchEvaluator(
                model_path=base_model_dir,
                tasks_dir=tasks_dir,
                tasks=mmlu_tasks,
                few_shots=few_shots,
                batch_size=batch_size,
            ),
        ]
        m_paths = [candidate_model, base_model_dir]
        overall_scores = []
        individual_scores_list = []
        for i, evaluator in enumerate(mmlu_branch_evaluators):
            m_path = m_paths[i]
            launch_vllm(m_path, gpu_count)
            overall_score, individual_scores = evaluator.run(VLLM_SERVER)
            overall_scores.append(overall_score)
            individual_scores_list.append(individual_scores)
            stop_vllm()

        # TODO: update instructlab/instructlab model/evaluate.py
        # so this logic can be imported outside of the CLI
        overall_score = overall_scores[0]
        base_overall_score = overall_scores[1]
        individual_scores = individual_scores_list[0]
        base_individual_scores = individual_scores_list[1]

        improvements, regressions, no_changes = [], [], []
        for task, score in individual_scores.items():
            base_score = base_individual_scores[task]
            s = score["score"]
            b_s = base_score["score"]
            d = round(s - b_s, 2)
            if s > b_s:
                improvements.append((task, d, b_s, s))
            elif b_s > s:
                regressions.append((task, d, b_s, s))
            else:
                no_changes.append((task, s))

        summary = branch_eval_summary_to_json(
            improvements,
            regressions,
            no_changes,
        )

        mmlu_branch_data = {
            "report_title": "KNOWLEDGE EVALUATION REPORT",
            "max_score": "1.0",
            "model": candidate_model,
            "model_score": round(overall_score, 2),
            "base_model": base_model_dir,
            "base_model_score": round(base_overall_score, 2),
            "summary": summary,
        }

        with open(mmlu_branch_output.path, "w") as f:
            json.dump(mmlu_branch_data, f, indent=4)
    else:
        print("No MMLU tasks directories found, skipping MMLU_branch evaluation.")

    # MT_BENCH_BRANCH

    judge_api_key = os.getenv("JUDGE_API_KEY", "")
    judge_model_name = os.getenv("JUDGE_NAME")
    judge_endpoint = os.getenv("JUDGE_ENDPOINT")

    output_dir = "/tmp/eval_output"

    # TODO: candidate_branch must be in same repo, not a fork, or, can compare main branch against candidate, base models
    base_branch = base_branch or "main"
    candidate_branch = candidate_branch or "main"

    ######################################################################
    # TODO: Update ilab/model/evaluate evaluate def logic to allow for external judge model
    # and when that happens, much of this logic can be imported from the `evaluate` definition:
    # https://github.com/instructlab/instructlab/blob/83ca501ecdd858677380046e2a56da5b2f3f14e7/src/instructlab/model/evaluate.py#L504
    #
    # With instructlab, model_name is synonomous with model_path
    mt_bench_evaluators = [
        MTBenchBranchEvaluator(
            model_name=candidate_model,
            judge_model_name=judge_model_name,
            taxonomy_git_repo_path=taxonomy.path,
            branch=candidate_branch,
            output_dir=output_dir,
            merge_system_user_message=merge_system_user_message,
        ),
        MTBenchBranchEvaluator(
            model_name=base_model_dir,
            judge_model_name=judge_model_name,
            taxonomy_git_repo_path=taxonomy.path,
            branch=base_branch,
            output_dir=output_dir,
            merge_system_user_message=merge_system_user_message,
        ),
    ]

    # ilab/evaluate uses a magic word for its mt_bench evaluator  - `auto`
    # with `auto`, number of gpus allocated for serving is calculated based on environment
    # https://github.com/instructlab/eval/blob/main/src/instructlab/eval/mt_bench.py#L36
    if max_workers == "auto":
        try:
            usable_cpu_count = len(os.sched_getaffinity(0)) // 2
        except AttributeError:
            usable_cpu_count = multiprocessing.cpu_count() // 2
        max_workers = usable_cpu_count

    branches = [candidate_branch, base_branch]
    m_paths = [candidate_model, base_model_dir]
    qa_pairs_and_errors = []
    for i, evaluator in enumerate(mt_bench_evaluators):
        branch = branches[i]
        m_path = m_paths[i]

        print(
            f"Generating questions and reference answers from qna files for branch {branch}..."
        )
        launch_vllm(m_path, gpu_count)

        evaluator.gen_answers(
            server_url=VLLM_SERVER,
            serving_gpus=gpu_count,
            max_workers=max_workers,
        )

        stop_vllm()

        print(f"Evaluating answers for branch {branch}...")
        overall_score, qa_pairs, error_rate = evaluator.judge_answers(
            server_url=judge_endpoint,
            api_key=judge_api_key,
            serving_gpus=gpu_count,
            max_workers=max_workers,
        )

        qa_pairs_and_errors.append((overall_score, qa_pairs, error_rate))

    overall_score, qa_pairs, error_rate = qa_pairs_and_errors[0]
    base_overall_score, base_qa_pairs, base_error_rate = qa_pairs_and_errors[1]

    qna_to_avg_scores = qa_pairs_to_qna_to_avg_scores(qa_pairs)
    base_qna_to_avg_scores = qa_pairs_to_qna_to_avg_scores(base_qa_pairs)

    improvements, regressions, no_changes, new_qnas = [], [], [], []

    for qna, avg_score in qna_to_avg_scores.items():
        base_avg_score = base_qna_to_avg_scores.get(qna)
        if base_avg_score is not None:
            if avg_score > base_avg_score:
                improvements.append(
                    (
                        qna,
                        round(avg_score - base_avg_score, 2),
                        base_avg_score,
                        avg_score,
                    )
                )
            elif avg_score == base_avg_score:
                no_changes.append((qna, avg_score))
            else:
                regressions.append(
                    (
                        qna,
                        round(avg_score - base_avg_score, 2),
                        base_avg_score,
                        avg_score,
                    )
                )
        else:
            new_qnas.append((qna, avg_score))

    error_rate = (error_rate + base_error_rate) / 2
    if error_rate > 0:
        error_rate = round(error_rate, 2)

    summary = branch_eval_summary_to_json(
        improvements,
        regressions,
        no_changes,
        new_qnas,
    )

    mt_bench_branch_data = {
        "report_title": "SKILLS EVALUATION REPORT",
        "model": candidate_model,
        "judge_model": judge_model_name,
        "max_score": "10.0",
        "overall_score": overall_score,
        "base_overall_score": base_overall_score,
        "error_rate": error_rate,
        "summary": summary,
    }

    with open(mt_bench_branch_output.path, "w") as f:
        json.dump(mt_bench_branch_data, f, indent=4)
