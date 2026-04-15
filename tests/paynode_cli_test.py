import os
import json
import typer
import requests
import time
from typing import Optional, List
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint
from paynode_sdk import PayNodeAgentClient, SDK_VERSION
from paynode_sdk.constants import (
    BASE_RPC_URLS, 
    BASE_RPC_URLS_SANDBOX, 
    BASE_USDC_ADDRESS, 
    BASE_USDC_ADDRESS_SANDBOX
)
from paynode_sdk.errors import PayNodeException
from eth_account import Account
from dotenv import load_dotenv

load_dotenv()

app = typer.Typer(help=f"PayNode CLI (Python) v{SDK_VERSION} - Testing Tool")
console = Console()

def get_client(network: str = "testnet"):
    private_key = os.getenv("CLIENT_PRIVATE_KEY")
    if not private_key:
        rprint("[bold red]Error:[/bold red] CLIENT_PRIVATE_KEY environment variable is not set.")
        raise typer.Exit(code=1)
    
    rpc_urls = BASE_RPC_URLS_SANDBOX if network == "testnet" else BASE_RPC_URLS
    return PayNodeAgentClient(private_key=private_key, rpc_urls=rpc_urls)

@app.command()
def version():
    """Show the version info."""
    rprint(f"PayNode SDK (Python) [bold green]v{SDK_VERSION}[/bold green]")
    rprint(f"CLI Testing Tool active.")

@app.command()
def check(
    network: str = typer.Option("testnet", help="Network: mainnet or testnet"),
    json_output: bool = typer.Option(False, "--json", help="Output in machine-readable JSON")
):
    """Check wallet balance and readiness on Base L2."""
    client = get_client(network)
    address = client.account.address
    
    try:
        eth_balance = client.w3.eth.get_balance(address)
        eth_val = client.w3.from_wei(eth_balance, 'ether')
        
        usdc_addr = BASE_USDC_ADDRESS_SANDBOX if network == "testnet" else BASE_USDC_ADDRESS
        usdc_abi = [{"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"}]
        usdc_contract = client.w3.eth.contract(address=usdc_addr, abi=usdc_abi)
        usdc_balance = usdc_contract.functions.balanceOf(address).call()
        usdc_val = usdc_balance / 10**6
        
        if json_output:
            console.print_json(data={
                "address": address,
                "network": network,
                "eth": str(eth_val),
                "usdc": str(usdc_val),
                "ready": eth_val > 0 and usdc_val > 0
            })
        else:
            table = Table(title=f"PayNode Wallet Readiness ({network})")
            table.add_column("Asset", style="cyan")
            table.add_column("Balance", style="magenta")
            table.add_column("Address", style="dim")
            
            table.add_row("ETH", f"{eth_val:.6f}", address)
            table.add_row("USDC", f"{usdc_val:.2f}", usdc_addr)
            
            console.print(table)
            
            if eth_val == 0:
                rprint("[yellow]Warning:[/yellow] No gas (ETH) found. Please fund your wallet.")
            if usdc_val == 0:
                rprint("[yellow]Warning:[/yellow] No USDC found. Use 'mint' command on testnet.")

    except Exception as e:
        rprint(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)

@app.command()
def mint(
    amount: int = typer.Option(100, help="Amount of Mock USDC to mint (testnet only)"),
    network: str = typer.Option("testnet", help="Network (must be testnet)")
):
    """Mint Mock USDC on Base Sepolia (Testnet)."""
    if network != "testnet":
        rprint("[bold red]Error:[/bold red] Minting is only available on testnet.")
        raise typer.Exit(code=1)
    
    client = get_client(network)
    account = Account.from_key(os.getenv("CLIENT_PRIVATE_KEY"))
    rprint(f"Minting [bold cyan]{amount} USDC[/bold cyan] for [bold magenta]{account.address}[/bold magenta]...")
    
    try:
        abi = [{"inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "mint", "outputs": [], "stateMutability": "nonpayable", "type": "function"}]
        usdc = client.w3.eth.contract(address=BASE_USDC_ADDRESS_SANDBOX, abi=abi)

        mint_amount = amount * 10**6
        rprint("⏳ Sending mint transaction...")
        tx = usdc.functions.mint(account.address, mint_amount).build_transaction({
            'from': account.address,
            'nonce': client.w3.eth.get_transaction_count(account.address),
            'gas': 100000,
            'gasPrice': int(client.w3.eth.gas_price * 1.2)
        })
        
        signed_tx = account.sign_transaction(tx)
        tx_hash = client.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        
        rprint(f"🚀 Mint Transaction Sent! Hash: [dim]{client.w3.to_hex(tx_hash)}[/dim]")
        rprint("⏳ Waiting for confirmation...")
        
        receipt = client.w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status == 1:
            rprint(f"[bold green]✅ SUCCESS![/bold green] You now have +{amount} Test USDC.")
        else:
            rprint("[bold red]❌ FAILED:[/bold red] Minting failed. Check block explorer.")

    except Exception as e:
        rprint(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)

@app.command()
def request(
    url: str = typer.Argument(..., help="Target URL protected by PayNode"),
    network: str = typer.Option("testnet", help="Network: mainnet or testnet"),
    method: str = typer.Option("GET", help="HTTP method (GET, POST, etc.)"),
    confirm: bool = typer.Option(False, "--confirm-mainnet", help="Confirm real transaction on mainnet"),
    json_output: bool = typer.Option(False, "--json", help="Output in machine-readable JSON")
):
    """Request a 402-protected resource manually."""
    if network == "mainnet" and not confirm:
        rprint("[bold red]Error:[/bold red] Mainnet requests require --confirm-mainnet flag.")
        raise typer.Exit(code=1)
    
    client = get_client(network)
    
    if not json_output:
        rprint(f"🚀 [cyan]Handshaking ({method}) with {url}...[/cyan]")
    
    try:
        response = client.request_gate(url, method=method)
        
        if response.status_code == 200:
            if json_output:
                console.print_json(data=response.json())
            else:
                rprint("[bold green]✅ Success![/bold green] Response received:")
                console.print(Panel(json.dumps(response.json(), indent=2), title="Resource Content", border_style="green"))
        else:
            rprint(f"[bold red]❌ Failed![/bold red] Status Code: {response.status_code}")
            console.print(response.text)
            raise typer.Exit(code=1)
            
    except PayNodeException as e:
        rprint(f"[bold red]Protocol Error:[/bold red] {e}")
        raise typer.Exit(code=1)
    except Exception as e:
        rprint(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)

marketplace_app = typer.Typer(help="Marketplace commands to discover and invoke paid APIs.")
app.add_typer(marketplace_app, name="marketplace")

@marketplace_app.command(name="list")
def list_apis(
    market_url: str = typer.Option("https://mk.paynode.dev", help="Marketplace URL"),
    network: str = typer.Option("testnet", help="Network"),
    json_output: bool = typer.Option(False, "--json", help="Output in machine-readable JSON")
):
    """List available APIs from the catalog."""
    try:
        resp = requests.get(f"{market_url}/api/v1/paid-apis", params={"network": network})
        resp.raise_for_status()
        data = resp.json()
        
        items = data.get("items", []) if isinstance(data, dict) else data
        
        if json_output:
            console.print_json(data=items)
        else:
            table = Table(title="PayNode Catalog APIs")
            table.add_column("ID", style="dim")
            table.add_column("Name", style="bold")
            table.add_column("Price", style="magenta")
            table.add_column("Seller", style="cyan")
            
            for item in items:
                price = f"{item.get('price_per_call', 0)} {item.get('currency', 'USDC')}"
                seller = item.get("seller", {}).get("name") or "Unknown"
                table.add_row(
                    str(item.get("id")),
                    item.get("name"),
                    price,
                    seller
                )
            console.print(table)
    except Exception as e:
        rprint(f"[bold red]Error:[/bold red] {e}")

@marketplace_app.command(name="invoke")
def invoke_api(
    api_id: str = typer.Argument(..., help="API ID from marketplace"),
    market_url: str = typer.Option("https://mk.paynode.dev", help="Marketplace URL"),
    network: str = typer.Option("testnet", help="Network"),
    json_output: bool = typer.Option(False, "--json", help="Output JSON")
):
    """Invoke a marketplace API (automatic preparation and 402 flow)."""
    try:
        if not json_output:
            rprint(f"Preparing invocation for [bold yellow]{api_id}[/bold yellow]...")
            
        list_resp = requests.get(f"{market_url}/api/v1/paid-apis", params={"network": network})
        data = list_resp.json()
        items = data.get("items", []) if isinstance(data, dict) else data
        
        target_api = None
        for item in items:
            if item.get("id") == api_id or item.get("api_id") == api_id or item.get("slug") == api_id:
                target_api = item
                break
        
        if not target_api:
            rprint(f"[yellow]API '{api_id}' not found in catalog cache, attempting direct preparation...[/yellow]")
            invoke_url = f"{market_url}/proxy/{api_id}"
        else:
            invoke_url = target_api.get("payable_url") or target_api.get("invoke_url") or f"{market_url}/proxy/{target_api.get('slug')}"
            
        if not json_output:
            rprint(f"Invoking via: [bold cyan]{invoke_url}[/bold cyan]")

        # 2. Re-use request logic with correct method
        method = target_api.get("method", "GET") if target_api else "GET"
        request(url=invoke_url, network=network, json_output=json_output, method=method)
        
    except Exception as e:
        rprint(f"[bold red]Error:[/bold red] {e}")

if __name__ == "__main__":
    app()
