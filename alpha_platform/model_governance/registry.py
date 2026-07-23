import json
import hashlib
from datetime import datetime
from typing import Dict, List, Optional
from alpha_platform.core.types import ModelGovernanceRecord, StrategyStage
from alpha_platform.config.logging_config import logger

class ModelRegistry:
    def __init__(self):
        self._registry: Dict[str, ModelGovernanceRecord] = {}

    def register_model(
        self,
        model_id: str,
        version: str,
        dataset_content: bytes,
        features: List[str],
        parameters: Dict,
        brier_score: float,
        pbo_score: float,
        dsr_score: float
    ) -> ModelGovernanceRecord:
        dataset_hash = hashlib.sha256(dataset_content).hexdigest()
        
        record = ModelGovernanceRecord(
            model_id=model_id,
            version=version,
            training_date=datetime.utcnow().isoformat(),
            dataset_hash=dataset_hash,
            features=features,
            parameters=parameters,
            brier_score=brier_score,
            pbo_score=pbo_score,
            dsr_score=dsr_score,
            stage=StrategyStage.RESEARCH
        )
        self._registry[model_id] = record
        logger.info(f"Registered model '{model_id}' version '{version}' in stage '{record.stage}'")
        return record

    def promote_stage(self, model_id: str, target_stage: StrategyStage, override_approval: bool = False) -> bool:
        if model_id not in self._registry:
            logger.error(f"Model ID '{model_id}' not found in registry.")
            return False

        record = self._registry[model_id]

        # Production promotion gate requirements
        if target_stage == StrategyStage.PRODUCTION and not override_approval:
            if record.pbo_score >= 0.10 or record.dsr_score <= 1.5:
                logger.error(f"REJECTED promotion to PRODUCTION: PBO ({record.pbo_score:.2f}) must be < 0.10 and DSR ({record.dsr_score:.2f}) must be > 1.5")
                return False

        record.stage = target_stage
        logger.info(f"Model '{model_id}' successfully promoted to stage '{target_stage}'")
        return True

    def get_model(self, model_id: str) -> Optional[ModelGovernanceRecord]:
        return self._registry.get(model_id)

    def list_models(self) -> List[ModelGovernanceRecord]:
        return list(self._registry.values())
