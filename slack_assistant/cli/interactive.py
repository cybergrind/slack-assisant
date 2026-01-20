"""Interactive console for the status agent."""

import logging

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from slack_assistant.agent import AgentController, AgentResponse


logger = logging.getLogger(__name__)

console = Console()


def _create_key_bindings() -> KeyBindings:
    """Create key bindings for the prompt.

    Returns:
        KeyBindings with Ctrl+J for newline support.
    """
    bindings = KeyBindings()

    @bindings.add('c-j')
    def _(event):
        """Insert newline on Ctrl+J."""
        event.current_buffer.insert_text('\n')

    return bindings


class InteractiveConsole:
    """Interactive console for chatting with the agent."""

    def __init__(self, agent: AgentController):
        """Initialize the interactive console.

        Args:
            agent: The agent controller to use.
        """
        self._agent = agent
        self._running = False
        self._session = PromptSession(
            key_bindings=_create_key_bindings(),
            multiline=False,  # Enter submits, Ctrl+J adds newline
        )

    def _print_response(self, response: AgentResponse) -> None:
        """Print an agent response with rich formatting.

        Args:
            response: The agent response to print.
        """
        if response.text:
            # Render markdown
            md = Markdown(response.text)
            panel = Panel(
                md,
                title='Assistant',
                border_style='blue',
                padding=(1, 2),
            )
            console.print(panel)

        # Show metadata
        if response.tool_calls_made > 0 or response.tokens_used > 0:
            meta_parts = []
            if response.tool_calls_made > 0:
                meta_parts.append(f'{response.tool_calls_made} tool calls')
            if response.tokens_used > 0:
                meta_parts.append(f'{response.tokens_used} tokens')
            console.print(f'[dim]({", ".join(meta_parts)})[/dim]')

    def _print_help(self) -> None:
        """Print help message."""
        help_text = """**Available Commands:**

- `/quit` or `/exit` - Exit the agent
- `/clear` - Clear conversation history
- `/help` - Show this help message
- `/status` - Get fresh status update

**Input:**
- `Enter` - Send message
- `Ctrl+J` - Insert newline (for multi-line messages)

**Tips:**
- Ask about specific threads or messages
- Ask to search for topics
- Tell me to remember important follow-ups
- Ask for more details on any item
"""
        md = Markdown(help_text)
        console.print(Panel(md, title='Help', border_style='green'))

    async def _handle_command(self, command: str) -> bool:
        """Handle a slash command.

        Args:
            command: The command (including slash).

        Returns:
            True to continue, False to exit.
        """
        cmd = command.lower().strip()

        if cmd in ('/quit', '/exit', '/q'):
            console.print('[yellow]Goodbye![/yellow]')
            return False

        elif cmd in ('/clear', '/c'):
            self._agent.clear_conversation()
            console.print('[green]Conversation cleared.[/green]')

        elif cmd in ('/help', '/h', '/?'):
            self._print_help()

        elif cmd == '/status':
            console.print('[dim]Fetching fresh status...[/dim]')
            response = await self._agent.initialize()
            self._print_response(response)

        else:
            console.print(f'[red]Unknown command: {command}[/red]')
            console.print('[dim]Type /help for available commands.[/dim]')

        return True

    async def run(self) -> None:
        """Run the interactive console loop."""
        self._running = True

        # Print welcome message
        console.print()
        console.print(
            Panel.fit(
                '[bold blue]Slack Status Agent[/bold blue]\n'
                'Type [green]/help[/green] for commands or just ask questions.',
                border_style='blue',
            )
        )
        console.print()

        # Get initial status
        console.print('[dim]Initializing and checking status...[/dim]')
        try:
            response = await self._agent.initialize()
            self._print_response(response)
        except Exception as e:
            logger.exception('Failed to initialize agent')
            console.print(f'[red]Failed to initialize: {e}[/red]')
            return

        # Main loop
        while self._running:
            try:
                console.print()
                user_input = await self._session.prompt_async('You: ')

                if not user_input.strip():
                    continue

                # Handle commands
                if user_input.startswith('/'):
                    should_continue = await self._handle_command(user_input)
                    if not should_continue:
                        break
                    continue

                # Process regular message
                console.print('[dim]Thinking...[/dim]')
                try:
                    response = await self._agent.process_message(user_input)
                    self._print_response(response)
                except Exception as e:
                    logger.exception('Error processing message')
                    console.print(f'[red]Error: {e}[/red]')

            except KeyboardInterrupt:
                console.print('\n[yellow]Use /quit to exit[/yellow]')
            except EOFError:
                console.print('\n[yellow]Goodbye![/yellow]')
                break

        self._running = False


async def run_interactive(agent: AgentController) -> None:
    """Run the interactive console.

    Args:
        agent: The agent controller to use.
    """
    console_ui = InteractiveConsole(agent)
    await console_ui.run()
