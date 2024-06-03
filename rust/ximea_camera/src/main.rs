// External crate imports
use clap::Parser;
use crossbeam::channel;
use image::{ImageBuffer, Luma};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

// Local module declarations
mod frames;
mod helpers;
mod structs;
mod zmq_handler;

// Imports from local modules
use frames::frame_handler;
use helpers::*;
use structs::*;
use zmq_handler::Subscriber;

fn main() -> Result<(), i32> {
    // set logging level
    if std::env::var_os("RUST_LOG").is_none() {
        std::env::set_var("RUST_LOG", "info");
    }

    // setup logger
    env_logger::init();

    // setup ctrl-c handler
    let running = Arc::new(AtomicBool::new(true));
    setup_ctrlc_handler(running.clone());

    // Parse command line arguments
    let args = Args::parse();
    // Open the camera
    let mut cam = xiapi::open_device(Some(0))?;

    // Set camera parameters
    set_camera_parameters(&mut cam, &args)?;

    // calculate frames before and after
    let n_before = (args.t_before * args.fps) as usize;
    let n_after = (args.t_after * args.fps) as usize;
    log::debug!(
        "Recording {} frames before and {} after trigger",
        n_before,
        n_after
    );

    // Connect to ZMQ; return error if connection fails
    log::info!("Connecting to ZMQ server at {}", args.address);
    let ctx = zmq::Context::new();
    let socket = Subscriber::new(&ctx, args.sub_port, args.req_port, &args.address);
    socket.handshake();
    socket.subscribe("topic");

    // Get save folder
    let save_folder = args.save_folder;

    // spawn writer thread
    let (sender, receiver) = channel::unbounded::<(Arc<ImageData>, MessageType)>();
    let frame_handler =
        std::thread::spawn(move || frame_handler(receiver, n_before, n_after, save_folder));

    // create image buffer
    let buffer = cam.start_acquisition()?;
    //let mut image_data: Arc<ImageData> = Arc::new(ImageData::default());

    // start acquisition
    log::info!("Starting acquisition");
    while running.load(Ordering::SeqCst) {
        let msg = socket.receive(false).unwrap();

        // receive message
        let parsed_message = parse_message(&msg);

        // check if got "kill" in parsed_message
        if let MessageType::Text(data) = &parsed_message {
            if data == "kill" {
                break;
            }
        }

        // Get frame from camera
        let frame = buffer.next_image::<u8>(None)?;

        // Put frame data to struct
        let image_data = Arc::new(ImageData {
            width: frame.width(),
            height: frame.height(),
            nframe: frame.nframe(),
            acq_nframe: frame.acq_nframe(),
            timestamp_raw: frame.timestamp_raw(),
            exposure_time: frame.exposure_time_us(),
            data: ImageBuffer::<Luma<u8>, Vec<u8>>::from(frame),
        });

        // send frame with the incoming parsed message
        match sender.send((image_data, parsed_message)) {
            Ok(_) => {}
            Err(_e) => {} //log::error!("Failed to send frame: {}", e),
        }
    }

    // stop acquisition
    buffer.stop_acquisition()?;

    // send kill signal
    match sender.send((
        Arc::new(ImageData::default()),
        MessageType::Text("kill".to_string()),
    )) {
        Ok(_) => {
            log::info!("Sent kill message to frame handler");
        }
        Err(_e) => {
            log::error!("Failed to send kill trigger to frame handler.")
        }
    }

    // stop frame handler
    frame_handler.join().unwrap();

    Ok(())
}
