package com.horsecoder.common.whuTalent.core.flow;

import cc.eamon.open.flow.core.FlowEngine;
import cc.eamon.open.flow.core.stereotype.Flow;
import cc.eamon.open.flow.spring.FlowComponent;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

import java.io.IOException;

@FlowComponent
public class Task2AgentNodes {
    private static final String WORKER_URL = "http://127.0.0.1:3211/api/task2/step";
    private final ObjectMapper json = new ObjectMapper();
    private final RestTemplate worker;

    public Task2AgentNodes() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(3000);
        factory.setReadTimeout(190000);
        worker = new RestTemplate(factory);
    }

    @Flow("TASK2_SINGLE_GENERATE")
    public void singleGenerate(String question) throws IOException {
        put("sqlStep", request("single-table", "singer", question));
    }

    @Flow("TASK2_SINGLE_QUERY")
    public void singleQuery(String question, String sqlStep) throws IOException {
        put("result", request("single-table", "execute", question, sqlStep));
    }

    @Flow("TASK2_SINGER_ANALYZE")
    public void singerAnalyze(String question) throws IOException {
        put("singerStep", request("multi-agent", "singer", question));
    }

    @Flow("TASK2_CONCERT_ANALYZE")
    public void concertAnalyze(String question) throws IOException {
        put("concertStep", request("multi-agent", "singer_in_concert", question));
    }

    @Flow("TASK2_MULTI_GENERATE")
    public void multiGenerate(String question, String singerStep, String concertStep)
            throws IOException {
        put("sqlStep", request("multi-agent", "sql", question, singerStep, concertStep));
    }

    @Flow("TASK2_MULTI_QUERY")
    public void multiQuery(String question, String singerStep, String concertStep, String sqlStep)
            throws IOException {
        put("result", request("multi-agent", "execute", question, singerStep, concertStep, sqlStep));
    }

    private void put(String name, String output) {
        FlowEngine.instance().register(name, output);
    }

    private String request(String flowId, String agent, String question, String... previous)
            throws IOException {
        ObjectNode body = json.createObjectNode().put("flowId", flowId);
        ObjectNode params = body.putObject("params").put("agent", agent).put("question", question);
        ArrayNode steps = params.putArray("steps");
        for (String step : previous) {
            steps.add(json.readTree(step));
        }
        JsonNode response = worker.postForObject(WORKER_URL, body, JsonNode.class);
        if (response == null || !response.path("data").isObject()) {
            throw new IllegalStateException("任务二节点未返回数据");
        }
        return response.get("data").toString();
    }
}
