import json
from collections import deque
from core.interfaces import StrategyInterface, IndicatorInterface, OperatorInterface, ActionInterface
from core.registry import indicator_registry, operator_registry, action_registry

class GraphCompiler:
    def __init__(self, strategy_graph):
        self.strategy_graph = strategy_graph
        self.nodes = {node['id']: node for node in self.strategy_graph['nodes']}
        self.edges = self.strategy_graph['edges']
        self.validate()

    def validate(self):
        if "nodes" not in self.strategy_graph or "edges" not in self.strategy_graph:
            raise ValueError("Invalid strategy graph format")

    def _topological_sort(self):
        in_degree = {node_id: 0 for node_id in self.nodes}
        adj = {node_id: [] for node_id in self.nodes}

        for edge in self.edges:
            source_id = edge['source']
            target_id = edge['target']
            adj[source_id].append(target_id)
            in_degree[target_id] += 1

        queue = deque([node_id for node_id, degree in in_degree.items() if degree == 0])
        sorted_nodes = []

        while queue:
            node_id = queue.popleft()
            sorted_nodes.append(node_id)

            for neighbor_id in adj[node_id]:
                in_degree[neighbor_id] -= 1
                if in_degree[neighbor_id] == 0:
                    queue.append(neighbor_id)

        if len(sorted_nodes) != len(self.nodes):
            raise ValueError("Graph contains a cycle")

        return sorted_nodes

    def compile(self) -> StrategyInterface:
        sorted_node_ids = self._topological_sort()

        class CompiledStrategy(StrategyInterface):
            def __init__(self, graph_compiler, sorted_nodes):
                self.gc = graph_compiler
                self.sorted_nodes = sorted_nodes
                self.node_outputs = {}

            def on_bar_close(self, bar):
                for node_id in self.sorted_nodes:
                    node_info = self.gc.nodes[node_id]
                    node_type = node_info['type']
                    node_class = None
                    
                    if node_type in indicator_registry.get_all_indicators():
                        node_class = indicator_registry.get_indicator(node_type)
                    elif node_type in operator_registry.get_all_operators():
                        node_class = operator_registry.get_operator(node_type)
                    elif node_type in action_registry.get_all_actions():
                        node_class = action_registry.get_action(node_type)

                    if not node_class:
                        raise ValueError(f"Unknown node type: {node_type}")

                    instance = node_class()
                    
                    # Resolve inputs
                    inputs = []
                    for edge in self.gc.edges:
                        if edge['target'] == node_id:
                            source_node_id = edge['source']
                            source_output_key = edge.get('sourceHandle') # e.g. 'ema_value'
                            
                            if source_output_key:
                                inputs.append(self.node_outputs[source_node_id][source_output_key])
                            else: # Handle nodes with single output
                                inputs.append(list(self.node_outputs[source_node_id].values())[0])

                    # Execute node
                    if issubclass(node_class, IndicatorInterface):
                        # Indicators need the ohlcv data
                        output = instance.compute(bar, node_info.get('data', {}).get('params', {}))
                        self.node_outputs[node_id] = output
                    elif issubclass(node_class, OperatorInterface):
                        output = instance.compute(*inputs)
                        self.node_outputs[node_id] = {'output': output}
                    elif issubclass(node_class, ActionInterface):
                        if inputs and inputs[0]: # Trigger action if input is true
                            instance.execute(self) # Pass strategy instance for actions

        return CompiledStrategy(self, sorted_node_ids)
