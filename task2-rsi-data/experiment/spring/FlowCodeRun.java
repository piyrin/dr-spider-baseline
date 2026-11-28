package com.horsecoder.common.whuTalent.core.flow.Run.code;

import cc.eamon.open.flow.core.FlowEngine;
import cc.eamon.open.flow.core.stereotype.Flow;
import cc.eamon.open.flow.spring.FlowComponent;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import org.springframework.beans.factory.annotation.Value;

@FlowComponent
public class FlowCodeRun {
    @Value("${server.port}")
    private int serverPort;

    @Flow("FLOW_CODE_RUN")
    public void flowCodeRun(String structure) throws IOException {
        // A separate request keeps the case flow's engine context outside FLOW_RUN's scope.
        URL endpoint = new URL("http://127.0.0.1:" + serverPort + "/api/task2-experiment/case");
        HttpURLConnection connection = (HttpURLConnection) endpoint.openConnection();
        connection.setConnectTimeout(3000);
        connection.setReadTimeout(550000);
        connection.setRequestMethod("POST");
        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        connection.setDoOutput(true);
        try {
            try (OutputStream output = connection.getOutputStream()) {
                output.write(structure.getBytes(StandardCharsets.UTF_8));
            }
            int status = connection.getResponseCode();
            if (status != 200) throw new IOException("Task 2 case runner returned HTTP " + status);
            try (InputStream input = connection.getInputStream(); ByteArrayOutputStream result = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[8192];
                int count;
                while ((count = input.read(buffer)) != -1) result.write(buffer, 0, count);
                FlowEngine.instance().register("result", result.toString("UTF-8"));
            }
        } finally {
            connection.disconnect();
        }
    }
}
