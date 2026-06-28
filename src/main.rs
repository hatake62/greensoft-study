use std::net::TcpListener;
use std::io::Write;

fn main() {
    // 8080番ポートで待機
    let listener = TcpListener::bind("0.0.0.0:8080").unwrap();
    println!("Rust Idle Server is listening on port 8080...");

    // 通信が来たらシンプルな返事だけして、また待機に戻る
    for stream in listener.incoming() {
        match stream {
            Ok(mut stream) => {
                let response = "HTTP/1.1 200 OK\r\n\r\nHello from Rust!";
                let _ = stream.write_all(response.as_bytes());
            }
            Err(e) => println!("Error: {}", e),
        }
    }
}