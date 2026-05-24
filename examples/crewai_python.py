"""Intégration audit-bim-i3f dans CrewAI.

Pré-requis :
    pip install crewai crewai-tools mcp
"""
from crewai import Agent, Crew, Process, Task
from crewai_tools import MCPServerAdapter
from mcp import StdioServerParameters


def main():
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "audit_bim.mcp"],
        cwd="/Users/stani/code/MCP/audit-bim-i3f",
    )
    with MCPServerAdapter(server_params) as mcp_tools:
        auditor = Agent(
            role="AMO BIM I3F senior",
            goal="Auditer une maquette IFC contre le CCH I3F V3.6",
            backstory=(
                "Expert AMO BIM, parfaite connaissance du Cahier des "
                "Charges I3F (codifications, listes, Psets attendus)."
            ),
            tools=mcp_tools,
            llm="gpt-4o",
            verbose=True,
        )
        report_task = Task(
            description=(
                "1) Lance full_audit en phase AVP. "
                "2) Synthétise les anomalies par sévérité. "
                "3) Propose les 5 actions correctives prioritaires."
            ),
            expected_output="Rapport synthétique en français.",
            agent=auditor,
        )
        crew = Crew(
            agents=[auditor],
            tasks=[report_task],
            process=Process.sequential,
            verbose=True,
        )
        result = crew.kickoff()
        print(result)


if __name__ == "__main__":
    main()
