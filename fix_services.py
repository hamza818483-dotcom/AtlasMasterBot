with open('/data/data/com.termux/files/home/hf-deploy/services.py', 'r') as f:
    content = f.read()

old = '''    prompt_text = "\\n\\n".join(active_prompts)
    full_prompt = f"""{prompt_text}

{"Generate the ABSOLUTE MAXIMUM number of MCQs from this image. Extract MCQ from EVERY single line, fact, number, and piece of information. Do NOT stop until you have exhausted ALL content. Quality must be maintained." if count == 0 else f"You MUST generate EXACTLY {count} MCQs. Not less, not more. This is a strict requirement. Generate {count} MCQs from this image."}
Only use information present in the source. Do NOT create irrelevant questions.
Follow ALL rules from the prompts above.
Output ONLY valid JSON array:
[{{"question":"...","options":{{"A":"...","B":"...","C":"...","D":"..."}},"answer":"A/B/C/D","explanation":"... (max 165 chars Bengali)"}}]"""'''

new = '''    count_instruction = f"STRICT REQUIREMENT: Generate EXACTLY {count} MCQs. You MUST output exactly {count} items in the JSON array. No more, no less." if count > 0 else "Generate the ABSOLUTE MAXIMUM number of MCQs. Extract from EVERY line, fact, number. Do NOT stop early."
    prompt_text = "\\n\\n".join(active_prompts)
    full_prompt = f"""{count_instruction}

{prompt_text}

Only use information present in the source. Do NOT create irrelevant questions.
Output ONLY valid JSON array:
[{{"question":"...","options":{{"A":"...","B":"...","C":"...","D":"..."}},"answer":"A/B/C/D","explanation":"... (max 165 chars Bengali)"}}]"""'''

if old in content:
    content = content.replace(old, new)
    with open('/data/data/com.termux/files/home/hf-deploy/services.py', 'w') as f:
        f.write(content)
    print("✅ Fixed")
else:
    print("❌ Pattern not found")
    # Show current state
    import re
    m = re.search(r'prompt_text.*?JSON array.*?\]"""', content, re.DOTALL)
    if m: print(m.group()[:500])
