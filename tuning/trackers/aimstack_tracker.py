# Copyright The FMS HF Tuning Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Standard
import json
import logging
import os

# Third Party
from aim.hugging_face import AimCallback  # pylint: disable=import-error

# Local
from .tracker import Tracker
from tuning.config.tracker_configs import AimConfig

AIM_HASH_EXPORT_DEFAULT_FILENAME = "aimstack_tracker.json"


class RunIDExporterAimCallback(AimCallback):
    """
    Custom Aimstack callback is used to export run id from Aim
    as soon as it is created, which is during on_init_end.
    """

    # path where we export run hash generated by Aim
    # This is used to link back to the expriments from outside aimstack
    run_id_export_path = None
    logger = None

    # Override Aimstack callback on_init_end function
    # First call AimCallback.setup to initialize internal structures
    # second export Aimstack's run hash to a file
    # hash is exported to, AimConfig.aim_run_id_export_path if it is passed
    # or, training_args.output_dir/aimstack_tracker.json if output_dir is present
    # Exported hash looks like '{"run_hash":"<hash>"}' in the file
    # hash is not exported if both paths are invalid
    def on_init_end(self, args, state, control, **kwargs):
        """Override the `on_init_end` function in the `Aimstack` callback.

            This function performs the following steps:
            1. Calls `aim.hugging_face.AimCallback.setup` to
                initialize internal `aim` structures.
            2. Exports the `Aimstack` run hash:
                - If `AimConfig.aim_run_id_export_path` is provided, the hash is exported
                    to `AimConfig.aim_run_id_export_path/aimstack_tracker.json`
                - If `AimConfig.aim_run_id_export_path` is not provided but
                    `args.output_dir` is specified, the hash is exported to
                - If neither path is valid, the hash is not exported.

            The exported hash is formatted as '{"run_hash":"<hash>"}'.

        Args:
            For the arguments see reference to transformers.TrainingCallback
        """
        # pylint: disable=unused-argument
        self.setup()  # initialize aim's run_hash

        # Change default run hash path to output directory if not specified
        if self.run_id_export_path is None:
            if args is None or args.output_dir is None:
                self.logger.error(
                    "To export Aimstack hash either output_dir \
                                    or aim_run_id_export_path should be set"
                )
                return

            self.run_id_export_path = args.output_dir

        if not os.path.exists(self.run_id_export_path):
            os.makedirs(self.run_id_export_path, exist_ok=True)

        export_path = os.path.join(
            self.run_id_export_path, AIM_HASH_EXPORT_DEFAULT_FILENAME
        )
        with open(export_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"run_hash": str(self.experiment.hash)}))
            self.logger.info("Aimstack tracker run hash id dumped to " + export_path)


class AimStackTracker(Tracker):
    def __init__(self, tracker_config: AimConfig):
        """Tracker which uses Aimstack to collect and store metrics.

        Args:
            tracker_config (AimConfig): A valid AimConfig which contains either
            information about the repo or the server and port where aim db is present.
        """
        super().__init__(name="aim", tracker_config=tracker_config)
        # Get logger with root log level
        self.logger = logging.getLogger()

    def get_hf_callback(self):
        """Returns the aim.hugging_face.AimCallback object associated with this tracker.

        Raises:
            ValueError: If the config passed at initialise does not contain one of
                aim_repo or server and port where aim db is present.

        Returns:
            aim.hugging_face.AimCallback: The Aimcallback initialsed with the config
            provided at init time.
        """
        c = self.config
        exp = c.experiment
        url = c.aim_url
        repo = c.aim_repo
        run_id_path = c.aim_run_id_export_path

        if url is not None:
            aim_callback = RunIDExporterAimCallback(repo=url, experiment=exp)
        if repo:
            aim_callback = RunIDExporterAimCallback(repo=repo, experiment=exp)
        else:
            self.logger.error(
                "Aim tracker requested but repo or server is not specified. "
                + "Please specify either aim repo or aim server ip and port for using Aim."
            )
            raise ValueError(
                "Aim tracker requested but repo or server is not specified."
            )

        if aim_callback is not None:
            aim_callback.hash_export_path = run_id_path

        # let callback use the tracker logger
        aim_callback.logger = self.logger

        self.hf_callback = aim_callback
        return self.hf_callback

    def track(self, metric, name, stage="additional_metrics"):
        """Track any additional metric with name under Aimstack tracker.

        Args:
            metric (int/float): Expected metrics to be tracked by Aimstack.
            name (str): Name of the metric being tracked.
            stage (str, optional): Can be used to pass the namespace/metadata to
                associate with metric, e.g. at the stage the metric was generated like train, eval.
                Defaults to "additional_metrics".

        Raises:
            ValueError: If the metric or name are passed as None.
        """
        if metric is None or name is None:
            raise ValueError(
                "aimstack track function should not be called with None metric value or name"
            )
        context = {"subset": stage}
        callback = self.hf_callback
        run = callback.experiment
        if run is not None:
            run.track(metric, name=name, context=context)

    def set_params(self, params, name="extra_params"):
        """Attach any extra params with the run information stored in Aimstack tracker.

        Args:
            params (dict): A dict of k:v pairs of parameters to be storeed in tracker.
            name (str, optional): represents the namespace under which parameters
                will be associated in Aim. Defaults to "extra_params".

        Raises:
            ValueError: the params passed is None or not of type dict
        """
        if params is None:
            return
        if not isinstance(params, dict):
            raise ValueError(
                "set_params passed to aimstack should be called with a dict of params"
            )
        callback = self.hf_callback
        run = callback.experiment
        if run is not None:
            for key, value in params.items():
                run.set((name, key), value, strict=False)
