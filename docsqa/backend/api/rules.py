from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.models import Rule
from ..core.schemas import RuleResponse, RuleUpdate

router = APIRouter()


@router.get("/rules", response_model=List[RuleResponse])
async def list_rules(db: Session = Depends(get_db)):
    """List all rules"""
    
    rules = db.query(Rule).order_by(Rule.category, Rule.name).all()
    return [RuleResponse.from_orm(rule) for rule in rules]


@router.get("/rules/{rule_code}", response_model=RuleResponse)
async def get_rule(rule_code: str, db: Session = Depends(get_db)):
    """Get a specific rule"""
    
    rule = db.query(Rule).filter(Rule.rule_code == rule_code).first()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    return RuleResponse.from_orm(rule)


@router.patch("/rules/{rule_code}", response_model=RuleResponse)
async def update_rule(
    rule_code: str, 
    update_data: RuleUpdate, 
    db: Session = Depends(get_db)
):
    """Update a rule's configuration"""
    
    rule = db.query(Rule).filter(Rule.rule_code == rule_code).first()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    # Apply updates
    update_dict = update_data.dict(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(rule, field, value)
    
    db.commit()
    db.refresh(rule)
    
    return RuleResponse.from_orm(rule)


@router.get("/rules/categories", response_model=List[str])
async def get_rule_categories(db: Session = Depends(get_db)):
    """Get all rule categories"""
    
    categories = db.query(Rule.category).distinct().order_by(Rule.category).all()
    return [category[0] for category in categories]


@router.post("/rules/seed")
async def seed_default_rules(db: Session = Depends(get_db)):
    """Seed the database with default rules"""
    
    default_rules = [
        {
            "rule_code": "LINK_404",
            "name": "Broken Link (404)",
            "category": "links",
            "default_severity": "high",
            "config": {"timeout_ms": 4000}
        },
        {
            "rule_code": "LINK_TIMEOUT",
            "name": "Link Timeout",
            "category": "links", 
            "default_severity": "medium",
            "config": {"timeout_ms": 4000}
        },
        {
            "rule_code": "SDKVER_OLD",
            "name": "Outdated SDK Version",
            "category": "versions",
            "default_severity": "medium",
            "config": {"allow_majors_behind": 0, "allow_minors_behind": 1}
        },
        {
            "rule_code": "SDKVER_MAJOR",
            "name": "Major Version Behind",
            "category": "versions",
            "default_severity": "high",
            "config": {}
        },
        {
            "rule_code": "API_UNKNOWN",
            "name": "Unknown API Symbol",
            "category": "api",
            "default_severity": "medium",
            "config": {}
        },
        {
            "rule_code": "API_DEPRECATED",
            "name": "Deprecated API",
            "category": "api",
            "default_severity": "high",
            "config": {}
        },
        {
            "rule_code": "CLI_UNKNOWN",
            "name": "Unknown CLI Command", 
            "category": "cli",
            "default_severity": "medium",
            "config": {}
        },
        {
            "rule_code": "CLI_DEPRECATED",
            "name": "Deprecated CLI Command",
            "category": "cli",
            "default_severity": "high", 
            "config": {}
        },
        {
            "rule_code": "STYLE_NO_H1",
            "name": "Missing H1 Heading",
            "category": "style",
            "default_severity": "medium",
            "config": {}
        },
        {
            "rule_code": "STYLE_MULTIPLE_H1",
            "name": "Multiple H1 Headings",
            "category": "style",
            "default_severity": "low",
            "config": {}
        },
        {
            "rule_code": "STYLE_IMG_NO_ALT",
            "name": "Image Missing Alt Text",
            "category": "style",
            "default_severity": "medium",
            "config": {}
        },
        {
            "rule_code": "STYLE_TERMINOLOGY",
            "name": "Non-canonical Terminology",
            "category": "style",
            "default_severity": "low",
            "config": {}
        },
        {
            "rule_code": "LLM_SPELL",
            "name": "Spelling Error (LLM)",
            "category": "llm",
            "default_severity": "low",
            "config": {}
        },
        {
            "rule_code": "LLM_GRAMMAR",
            "name": "Grammar Issue (LLM)",
            "category": "llm",
            "default_severity": "low",
            "config": {}
        },
        {
            "rule_code": "LLM_CLARITY",
            "name": "Clarity Improvement (LLM)",
            "category": "llm",
            "default_severity": "medium",
            "config": {}
        },
        {
            "rule_code": "LLM_ACCURACY",
            "name": "Accuracy Issue (LLM)",
            "category": "llm",
            "default_severity": "high",
            "config": {}
        },
        {
            "rule_code": "LLM_CONSISTENCY",
            "name": "Consistency Issue (LLM)",
            "category": "llm",
            "default_severity": "medium",
            "config": {}
        },
        {
            "rule_code": "LLM_UNSURE",
            "name": "Uncertain Issue (LLM)",
            "category": "llm",
            "default_severity": "low",
            "config": {}
        }
    ]
    
    created_count = 0
    for rule_data in default_rules:
        existing = db.query(Rule).filter(Rule.rule_code == rule_data["rule_code"]).first()
        if not existing:
            rule = Rule(**rule_data)
            db.add(rule)
            created_count += 1
    
    db.commit()
    
    return {
        "message": f"Created {created_count} default rules",
        "total_rules": len(default_rules)
    }