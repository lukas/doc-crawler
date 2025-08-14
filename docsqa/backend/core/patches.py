import difflib
import re
from typing import List, Optional, Dict, Any
from io import StringIO


def create_unified_diff(original_content: str, modified_content: str, 
                       original_path: str = "original", modified_path: str = "modified",
                       lineterm: str = '') -> str:
    """Create a unified diff between two strings"""
    original_lines = original_content.splitlines(keepends=True)
    modified_lines = modified_content.splitlines(keepends=True)
    
    diff = difflib.unified_diff(
        original_lines,
        modified_lines,
        fromfile=original_path,
        tofile=modified_path,
        lineterm=lineterm
    )
    
    return ''.join(diff)


def create_line_replacement_patch(original_content: str, line_number: int, 
                                new_line: str, filepath: str) -> str:
    """Create a patch that replaces a specific line"""
    lines = original_content.splitlines(keepends=True)
    
    if line_number < 1 or line_number > len(lines):
        raise ValueError(f"Line number {line_number} is out of range")
    
    # Create modified content
    modified_lines = lines.copy()
    modified_lines[line_number - 1] = new_line + '\n' if not new_line.endswith('\n') else new_line
    
    original = ''.join(lines)
    modified = ''.join(modified_lines)
    
    return create_unified_diff(original, modified, filepath, f"{filepath} (modified)")


def apply_line_patch(original_content: str, line_start: int, line_end: int, 
                    new_content: str) -> str:
    """Apply a patch to specific lines"""
    lines = original_content.splitlines()
    
    # Validate line numbers
    if line_start < 1 or line_end < line_start or line_end > len(lines):
        raise ValueError(f"Invalid line range: {line_start}-{line_end}")
    
    # Replace the specified line range
    before_lines = lines[:line_start - 1]
    after_lines = lines[line_end:]
    new_lines = new_content.splitlines() if new_content else []
    
    result_lines = before_lines + new_lines + after_lines
    return '\n'.join(result_lines)


def parse_unified_diff(diff_content: str) -> List[Dict[str, Any]]:
    """Parse a unified diff and extract change information"""
    changes = []
    current_change = None
    
    for line in diff_content.splitlines():
        # File header
        if line.startswith('---'):
            if current_change:
                changes.append(current_change)
            current_change = {
                'original_file': line[4:].strip(),
                'modified_file': None,
                'hunks': []
            }
        elif line.startswith('+++'):
            if current_change:
                current_change['modified_file'] = line[4:].strip()
        # Hunk header
        elif line.startswith('@@'):
            if current_change:
                hunk_info = parse_hunk_header(line)
                current_change['hunks'].append({
                    'original_start': hunk_info['original_start'],
                    'original_count': hunk_info['original_count'],
                    'modified_start': hunk_info['modified_start'],
                    'modified_count': hunk_info['modified_count'],
                    'lines': []
                })
        # Content lines
        elif current_change and current_change['hunks']:
            current_hunk = current_change['hunks'][-1]
            if line.startswith('+'):
                current_hunk['lines'].append({'type': 'added', 'content': line[1:]})
            elif line.startswith('-'):
                current_hunk['lines'].append({'type': 'removed', 'content': line[1:]})
            elif line.startswith(' '):
                current_hunk['lines'].append({'type': 'context', 'content': line[1:]})
    
    if current_change:
        changes.append(current_change)
    
    return changes


def parse_hunk_header(hunk_line: str) -> Dict[str, int]:
    """Parse a diff hunk header line"""
    # Example: @@ -1,4 +1,4 @@
    pattern = r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@'
    match = re.match(pattern, hunk_line)
    
    if not match:
        raise ValueError(f"Invalid hunk header: {hunk_line}")
    
    original_start = int(match.group(1))
    original_count = int(match.group(2)) if match.group(2) else 1
    modified_start = int(match.group(3))
    modified_count = int(match.group(4)) if match.group(4) else 1
    
    return {
        'original_start': original_start,
        'original_count': original_count,
        'modified_start': modified_start,
        'modified_count': modified_count
    }


def validate_patch_scope(patch_content: str, allowed_line_start: int, 
                        allowed_line_end: int) -> bool:
    """Validate that a patch only affects allowed lines"""
    try:
        changes = parse_unified_diff(patch_content)
        
        for change in changes:
            for hunk in change['hunks']:
                # Check if hunk affects lines outside allowed range
                hunk_start = hunk['original_start']
                hunk_end = hunk_start + hunk['original_count'] - 1
                
                if hunk_start < allowed_line_start or hunk_end > allowed_line_end:
                    return False
        
        return True
    except Exception:
        return False


def extract_snippet_from_patch(patch_content: str) -> Optional[Dict[str, str]]:
    """Extract original and modified snippets from a patch"""
    try:
        changes = parse_unified_diff(patch_content)
        
        if not changes or not changes[0]['hunks']:
            return None
        
        # Take the first hunk
        hunk = changes[0]['hunks'][0]
        
        original_lines = []
        modified_lines = []
        
        for line_info in hunk['lines']:
            if line_info['type'] in ['context', 'removed']:
                original_lines.append(line_info['content'])
            if line_info['type'] in ['context', 'added']:
                modified_lines.append(line_info['content'])
        
        return {
            'original': '\n'.join(original_lines),
            'modified': '\n'.join(modified_lines)
        }
        
    except Exception:
        return None


def minimize_patch_context(patch_content: str, context_lines: int = 1) -> str:
    """Minimize the context in a patch to reduce noise"""
    try:
        changes = parse_unified_diff(patch_content)
        
        if not changes:
            return patch_content
        
        minimized_patches = []
        
        for change in changes:
            minimized_patches.append(f"--- {change['original_file']}")
            minimized_patches.append(f"+++ {change['modified_file']}")
            
            for hunk in change['hunks']:
                # Rebuild hunk with minimal context
                original_lines = []
                modified_lines = []
                context_before = []
                context_after = []
                changes_lines = []
                
                for i, line_info in enumerate(hunk['lines']):
                    if line_info['type'] == 'context':
                        if not changes_lines:  # Context before changes
                            context_before.append(line_info)
                            if len(context_before) > context_lines:
                                context_before.pop(0)
                        else:  # Context after changes
                            context_after.append(line_info)
                    else:  # Added or removed line
                        if context_after:
                            # We had some context after previous changes, add it
                            changes_lines.extend(context_after[:context_lines])
                            context_after = []
                        changes_lines.append(line_info)
                
                # Build minimized hunk
                minimized_lines = context_before + changes_lines + context_after[:context_lines]
                
                if minimized_lines:
                    # Calculate new hunk header
                    original_count = sum(1 for line in minimized_lines 
                                       if line['type'] in ['context', 'removed'])
                    modified_count = sum(1 for line in minimized_lines 
                                       if line['type'] in ['context', 'added'])
                    
                    hunk_header = f"@@ -{hunk['original_start']},{original_count} +{hunk['modified_start']},{modified_count} @@"
                    minimized_patches.append(hunk_header)
                    
                    for line_info in minimized_lines:
                        prefix = {'context': ' ', 'added': '+', 'removed': '-'}[line_info['type']]
                        minimized_patches.append(f"{prefix}{line_info['content']}")
        
        return '\n'.join(minimized_patches) + '\n'
        
    except Exception:
        # If minimization fails, return original
        return patch_content


def count_whitespace_changes(original_content: str, modified_content: str) -> int:
    """Count the number of lines that only have whitespace changes"""
    original_lines = original_content.splitlines()
    modified_lines = modified_content.splitlines()
    
    whitespace_only_changes = 0
    
    # Compare line by line
    max_lines = max(len(original_lines), len(modified_lines))
    
    for i in range(max_lines):
        original_line = original_lines[i] if i < len(original_lines) else ""
        modified_line = modified_lines[i] if i < len(modified_lines) else ""
        
        # If content is the same after stripping whitespace, it's a whitespace-only change
        if (original_line.strip() == modified_line.strip() and 
            original_line != modified_line):
            whitespace_only_changes += 1
    
    return whitespace_only_changes