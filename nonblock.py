"""Make all heavy handlers non-blocking"""
import asyncio
import functools

def nonblocking(func):
    """Decorator: Run function in background"""
    @functools.wraps(func)
    async def wrapper(update, context):
        # Create background task
        asyncio.create_task(func(update, context))
        # Immediately reply
        if update.message:
            await update.message.reply_text("✅ Task started! You can use other commands.")
        elif update.callback_query:
            await update.callback_query.answer("✅ Started!")
    return wrapper
